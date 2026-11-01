import json
import re
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import Field

from forge.builders import PROJECT
from forge.handoffs import record_handoff
from forge.schemas import Boundary,ImplementationPlan
from forge.workspace import OWNERS, FileOperation, safe_path, source_fingerprint, write_owned,plan_owners,normalize_app_source,app_coding_context,unsupported_imports


class RepairAnalysis(Boundary):
    diagnosis: str = Field(min_length=1, max_length=1000)
    recommendation: str = Field(min_length=1, max_length=1500)


class AppRepairAnalysis(RepairAnalysis):
    files: list[str] = Field(min_length=1,max_length=3)


class RepairState(TypedDict, total=False):
    analysis: dict


def builder_repair_context(requirements,plan,root,relative,feedback,analysis,affected):
    packet=app_coding_context(requirements,plan,root,relative,limit=13800,
        extra={**feedback,'qa':{'diagnosis':analysis.diagnosis,'recommendation':analysis.recommendation},
               'current_source_fingerprint':source_fingerprint(root)},required=True,priority=affected)
    # Keep the target separate so a small model cannot mistake every supplied file
    # for a requested output. Related code remains available for interface checks.
    packet['current_source']=packet['existing_source'].pop(relative)
    packet['reference_only_source']=packet.pop('existing_source')
    packet['output_scope']='Return only the complete replacement for file. Reference-only files must never be copied into the output.'
    if len(json.dumps(packet,separators=(',',':')))>14000:
        raise ValueError('Repair context exceeds the local coding context budget')
    return packet


def repair_job(job_id, agents, store):
    record = store.read(job_id)
    if record['status'] != 'VERIFICATION_FAILED':
        raise ValueError('Repair requires a recorded verification failure')
    attempts = sum(e['status'] == 'REPAIRING' for e in record['events'])
    if attempts >= 2:
        raise ValueError('Repair limit exhausted (maximum two)')
    evidence = next(e['payload'] for e in reversed(record['events']) if e['status']=='VERIFICATION_FAILED')
    report = json.loads(Path(evidence['report']).read_text(encoding='utf-8'))
    root = PROJECT / 'workspace' / job_id
    if source_fingerprint(root) != report['source_fingerprint']:
        raise ValueError('Source changed since failure; verify again before repairing')
    failed = [r for r in report.get('checks',{}).get('results',[]) if r['exit_code'] != 0]
    if not failed:
        raise ValueError('No application check failure: investigate the execution environment')
    logs = '\n'.join(r['output'] for r in failed)[:6000]
    review=next((e['payload'] for e in reversed(record['events']) if e['status']=='PLAN_REVIEW'),None)
    generic=bool(review and review['plan'].get('spec_version')==2)
    owners=plan_owners(ImplementationPlan.model_validate(review['plan'])) if generic else OWNERS
    allowed = set().union(*owners.values())
    affected = sorted(path for path in allowed if re.search(re.escape(path) + r'(?:\(|:)', logs))
    if generic:
        # Keep all failing check names, but bound their untrusted output separately.
        remaining=3000;failures=[]
        for item in failed:
            output=item.get('output','')[:remaining];remaining-=len(output)
            failures.append({'name':item['name'],'exit_code':item['exit_code'],
                             'output':output,'output_truncated':len(output)<len(item.get('output',''))})
        previous=next((e['payload'] for e in reversed(record['events']) if e['status']=='REPAIR_DIAGNOSIS'),None)
        feedback={'failures':failures,'previous_diagnosis':previous,
                  'failure_source_fingerprint':report['source_fingerprint']}
        context=app_coding_context(review['requirements'],review['plan'],root,'',extra=feedback,priority=affected)
        record_handoff(store,job_id,'verification','qa',
                       'Diagnose actual failing checks using the approved contract, current source and previous repair diagnosis.',context)
        analysis=AppRepairAnalysis.model_validate(agents.generate(AppRepairAnalysis,
            'You are the QA subagent. Diagnose actual compiler/build/HTTP acceptance failures '
            'and operator-recorded browser failures. '
            'Select at most three existing approved source files for a minimal repair. '
            'Select only files that need to change to resolve the observed failure, not already-correct callers. '
            'Never change tests, requirements, dependencies, readiness or ownership. Return diagnosis, '
            'recommendation and files from the supplied manifest. Do not claim success.',
            context,coding=True))
        if not set(analysis.files).issubset(allowed):raise ValueError('QA repair selection exceeds approved ownership')
        # Preserve helper-before-entrypoint order across owners and repeated repairs.
        affected=sorted(set(analysis.files),key=lambda path:(not path.startswith('lib/'),path.endswith('/page.tsx'),path))
        store.event(job_id,'REPAIRING',{'attempt':attempts+1,'strategy':'app_contract_model_edit','files':affected,
                                      'failed_checks':[r['name'] for r in failed],'source_fingerprint':report['source_fingerprint']})
        store.event(job_id,'REPAIR_DIAGNOSIS',{'attempt':attempts+1,**analysis.model_dump(),
                                            'source_fingerprint':report['source_fingerprint']},update_status=False)
        try:
            for relative in affected:
                owner=next(owner for owner,files in owners.items() if relative in files)
                # Re-read disk after every preceding edit; never reuse a stale source snapshot.
                data=builder_repair_context(review['requirements'],review['plan'],root,relative,feedback,analysis,affected)
                record_handoff(store,job_id,'qa',f'{owner}_builder',
                               f'Repair {relative} from the QA diagnosis and fresh source. Verification must run again.',data)
                result=FileOperation.model_validate(agents.generate(FileOperation,
                    f'You are the {owner} repair subagent. Return the complete corrected TypeScript '
                    f'file {relative} in content. Preserve the approved app contracts. Use Node 24 '
                    'node:sqlite correctly; StatementSync has no finalize(). Never replace the app '
                    'with a task template. No changes to tests, dependencies or other files. '
                    'Resolve the reported behavior, not just compilation. current_source is the ONLY '
                    'file to replace. reference_only_source contains other agents\' files for reading '
                    'interfaces only. Never concatenate multiple files. QA may discuss other files; '
                    'other calls handle those files. Output real source text in content, not a '
                    'second JSON-encoded string. Preserve this file\'s exports; do not add exports '
                    'belonging to another file. Return one JSON object with content only.',
                    data,coding=True))
                normalized=normalize_app_source(relative,result.content)
                rejected=unsupported_imports(root,relative,normalized)
                if rejected:raise ValueError('Repair imports unsupported dependencies: '+', '.join(rejected))
                if normalized!=result.content:
                    store.event(job_id,'SOURCE_ADJUSTED',{'file':relative,'rule':'platform-source-normalization','actor':'framework_controller'},update_status=False)
                write_owned(root,owner,relative,normalized,owners)
            store.event(job_id,'GENERATED_UNVERIFIED',{'workspace':str(root),'source_fingerprint':source_fingerprint(root),'repair_attempt':attempts+1})
        except Exception as exc:store.event(job_id,'FAILED',{'reason':str(exc)[:2000],'error_type':type(exc).__name__})
        return store.read(job_id)
    if not affected:
        raise ValueError('No safely attributable compiler locations; targeted repair requires review')
    strategy = 'targeted_model_edit' if attempts == 0 else 'trusted_template_restore'
    store.event(job_id,'REPAIRING',{'attempt':attempts+1,'strategy':strategy,'files':affected,'failed_checks':[r['name'] for r in failed],'source_fingerprint':report['source_fingerprint']})

    def qa(_state):
        analysis = RepairAnalysis.model_validate(agents.generate(RepairAnalysis,
            'You are the QA Agent. Interpret actual compiler errors and recommend a minimal repair. '
            'Do not claim success, change tests, add dependencies, or expand scope. '
            'On attempt two, the fixed policy restores only implicated files from the trusted '
            'supported template. Explain the applicable repair and its limitations.',
            {'failures':failed,'affected_files':affected,'strategy':strategy}))
        return {'analysis':analysis.model_dump()}

    def patch(state):
        for relative in affected:
            owner = next(owner for owner, files in owners.items() if relative in files)
            current = safe_path(root,relative).read_text(encoding='utf-8')
            reference = safe_path(PROJECT / 'templates' / 'task-app', relative).read_text(encoding='utf-8')
            if strategy == 'trusted_template_restore':
                write_owned(root,owner,relative,reference)
                continue
            result = FileOperation.model_validate(agents.generate(FileOperation,
                f'You are the {owner} repair subagent. Repair only {relative}. Return the complete '
                'TypeScript file in content. Preserve the reference template exports and signatures. '
                'Remove accidental additions unrelated to this file. The reference uses the correct '
                'node:sqlite API: StatementSync has no finalize(), all() and get() take no generic '
                'type arguments. lib/db.ts should export getDb() only; task CRUD belongs in lib/tasks.ts. '
                'Collection route.ts exports only GET and POST; item methods belong in [id]/route.ts. '
                'Use reference code when it already satisfies the contract. Never alter tests or dependencies.',
                {'current':current,'reference':reference,'qa':state['analysis'],'compiler_output':logs},coding=True))
            write_owned(root,owner,relative,result.content)
        return {}

    graph = StateGraph(RepairState)
    graph.add_node('qa_agent',qa)
    graph.add_node('targeted_builder_repair',patch)
    graph.add_edge(START,'qa_agent'); graph.add_edge('qa_agent','targeted_builder_repair'); graph.add_edge('targeted_builder_repair',END)
    try:
        with tracing_context(enabled=False):
            graph.compile().invoke({}, {'recursion_limit':6})
        store.event(job_id,'GENERATED_UNVERIFIED',{'workspace':str(root),'source_fingerprint':source_fingerprint(root),'repair_attempt':attempts+1})
    except Exception as exc:
        store.event(job_id,'FAILED',{'reason':str(exc)[:2000],'error_type':type(exc).__name__})
    return store.read(job_id)
