"""Independent requirements-derived assertions feeding the existing source repair loop."""
from forge.execution_models import execution_model
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from forge.acceptance_browser import harness_fingerprint,passed_report,run_acceptance_browser
from forge.acceptance_coverage import review_coverage
from forge.acceptance_review import review_suite
from forge.autonomous_acceptance import acceptance_worker,load_acceptance,suite_fingerprint,proposal_context
from forge.autonomous_build import PROJECT,_runtime_unchanged
from forge.autonomous_planning import AppDraft
from forge.autonomous_review import approved_review
from forge.coordinator import TaskCoordinator
from forge.senior_review import SeniorReviewer
from forge.runtime_reference import runtime_references
from forge.repair_routing import compiler_repair_owner
from forge.source_agent import SourceAgent,build_evidence
from forge.source_checks import run_source_checks,harness_fingerprint as build_harness_fingerprint
from forge.tasks import Dependency,Observation,Task,TaskLedger
from forge.workspace import safe_path,source_fingerprint
from forge.workspace_tools import WorkspaceTools


def tests_resumable(record,store,*,workspace_boundary=None):
    if record['status']!='AUTONOMOUS_TEST_PAUSED':return False
    try:
        review=approved_review(record['job_id'],store)
        pending=next(e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_TEST_PAUSED')
        ledger=TaskLedger(store,record['job_id']);state=ledger.read(pending['task_id'])
        for qa in ledger.list():
            if qa.task.parent_id==state.task.parent_id and qa.task.inputs.get('stage')=='acceptance_plan' and qa.status=='completed':
                load_acceptance(ledger,qa,review)
        root=safe_path(Path(workspace_boundary) if workspace_boundary else PROJECT/'workspace',record['job_id'])
        return (_runtime_unchanged(root) and state.inflight_role is None and state.status=='paused'
            and state.task.inputs.get('review_fingerprint')==review['fingerprint'])
    except (ValueError,OSError,KeyError,TypeError,StopIteration):return False


def current_failure_for_repair(state,root,contract):
    """Reuse only intact failed evidence for diagnosis, never as passing evidence."""
    try:
        observation=state.observations[-1]
        if observation.revision!=state.revision or observation.error or observation.fingerprint!=source_fingerprint(root):return False
        check=observation.checks[0]
        if check.check!='isolated_build' or check.exit_code==0:return False
        result=json.loads(Path(check.report).read_text(encoding='utf-8'))
        build=Path(result['build_report']);browser=Path(result['acceptance_report'])
        built=json.loads(build.read_text(encoding='utf-8'));seen=json.loads(browser.read_text(encoding='utf-8'))
        return bool(result['passed'] is False and built['passed'] is True and seen['passed'] is False and not result['cleanup_errors']
            and result['source_fingerprint']==observation.fingerprint==built['source_fingerprint']==seen['source_fingerprint']
            and result['contract_fingerprint']==contract['fingerprint']==seen['contract_fingerprint']
            and hashlib.sha256(build.read_bytes()).hexdigest()==result['build_report_sha256']
            and hashlib.sha256(browser.read_bytes()).hexdigest()==result['acceptance_report_sha256']
            and built['harness_fingerprint']==build_harness_fingerprint()
            and result['acceptance_harness_fingerprint']==seen['harness_fingerprint']==harness_fingerprint()
            and result['image']==built['image']==seen['app_image'])
    except (ValueError,OSError,KeyError,TypeError,IndexError):return False


def test_app(job_id,agents,store,*,resume=False,retry_coverage=False,run_selected=False,recheck=False,additional_actions=8,workspace_boundary=None,
             check_runner=run_source_checks,browser_runner=run_acceptance_browser):
    record=store.read(job_id)
    if sum(map(bool,[resume,retry_coverage,run_selected,recheck]))>1:raise ValueError('Choose one saved verification action')
    expected='AUTONOMOUS_CHECKS_BLOCKED' if retry_coverage or run_selected else 'AUTONOMOUS_TEST_PAUSED' if resume else 'AUTONOMOUS_BUILD_CHECKS_PASSED'
    allowed={'AUTONOMOUS_APP_CHECKS_PASSED','PREVIEW_STOPPED','PREVIEW_FAILED'} if recheck else {expected}
    if record['status'] not in allowed:raise ValueError('App checks require a built approved app or explicit saved test resume')
    review=approved_review(job_id,store)
    if agents.model_name!=execution_model(job_id,store,review):raise ValueError('Use the approved job model for QA/repair')
    boundary=Path(workspace_boundary) if workspace_boundary else PROJECT/'workspace';root=safe_path(boundary,job_id)
    draft=AppDraft.model_validate(review['draft']);ledger=TaskLedger(store,job_id)
    def authorize():
        if approved_review(job_id,store)['fingerprint']!=review['fingerprint'] or not _runtime_unchanged(root):
            raise ValueError('Approved plan or workspace runtime changed during app checks')
    authorize()
    resource_resume=False
    if resume:
        if not tests_resumable(record,store,workspace_boundary=boundary):raise ValueError('Inspect interrupted QA work before resuming')
        pending=next(e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_TEST_PAUSED')
        paused_state=ledger.read(pending['task_id'])
        resource_resume=paused_state.pause_kind=='provider_resource'
        ledger.resume(paused_state,additional_actions=additional_actions)
    parents=[state for state in ledger.list() if state.task.inputs.get('stage')=='approved_acceptance']
    if len(parents)>1:raise ValueError('Duplicate acceptance execution needs reconciliation')
    if not parents:
        built=next(e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_BUILD_CHECKS_PASSED')
        parent=ledger.start(ledger.create(Task(owner='coordinator',goal='Verify approved app behavior with independent frozen assertions.',
            inputs={'stage':'approved_acceptance','review_fingerprint':review['fingerprint']},
            dependencies=[Dependency(task_id=built['task_id'],revision=ledger.read(built['task_id']).revision)],required_checks=['isolated_build'])))
    else:parent=parents[0]
    if parent.task.inputs['review_fingerprint']!=review['fingerprint']:raise ValueError('Acceptance run belongs to another review')
    if (run_selected or recheck) and parent.status=='completed':parent=ledger.start(ledger.revise(parent,parent.task))
    context={key:review['binding']['inputs'].get(key,[] if key!='original_request' else '')
        for key in ['original_request','human_clarifications','human_review_feedback']}
    store.event(job_id,'AUTONOMOUS_TESTING',{'task_id':parent.task.id,
        'scope':'Define requirements-derived checks, then execute and repair against the frozen contract. No preview or release.'})
    def child(stage,owner,goal,inputs,dependencies,checks):
        matches=[state for state in ledger.list() if state.task.parent_id==parent.task.id and state.task.inputs.get('stage')==stage]
        if len(matches)>1:raise ValueError('Duplicate QA stage needs reconciliation')
        if matches and matches[0].status=='needs_refresh':
            saved=matches[0];saved=ledger.revise(saved,saved.task.model_copy(update={'dependencies':dependencies,
                'inputs':{**saved.task.inputs,**inputs}}))
            return ledger.resume(ledger.pause(saved,'Refresh verification after QA revision'),additional_actions=additional_actions)
        return matches[0] if matches else ledger.create(Task(parent_id=parent.task.id,owner=owner,goal=goal,
            inputs={**context,**inputs,'stage':stage,'review_fingerprint':review['fingerprint']},
            dependencies=dependencies,required_checks=checks),action_limit=8)
    def pause(state):
        authorize();store.event(job_id,'AUTONOMOUS_TEST_PAUSED',{'task_id':state.task.id,'reason':state.pause_reason or state.status,
            'source_fingerprint':source_fingerprint(root),'scope':'Saved app-check work; no readiness or release claim.'})
        return store.read(job_id)
    qa=child('acceptance_plan','qa','Define independent executable assertions from the approved request.',{},
        [Dependency(task_id=review['binding']['task_id'],revision=review['binding']['revision'])],['acceptance_contract'])
    if retry_coverage:
        prior=load_acceptance(ledger,qa,review)
        if not prior['suite']['uncovered']:raise ValueError('There is no unsupported coverage to re-evaluate')
        qa=ledger.revise(qa,qa.task)
        qa=ledger.resume(ledger.pause(qa,'Re-evaluate unsupported claims without changing approved requirements'),additional_actions=additional_actions)
    qa=TaskCoordinator(ledger,{'qa':lambda state:acceptance_worker(ledger,state,agents,review,authorize,
        lambda suite:review_coverage(ledger,state,agents,review,suite,authorize),
        lambda suite:review_suite(ledger,state,agents,review,suite,authorize))},
        SeniorReviewer(agents,ledger,{'qa'},context_loader=lambda current:proposal_context(ledger,current,review)),
        lambda:suite_fingerprint(ledger,ledger.read(qa.task.id))).run(qa.task.id)
    if qa.status!='completed':return pause(qa)
    contract=load_acceptance(ledger,qa,review)
    store.event(job_id,'AUTONOMOUS_ACCEPTANCE_FROZEN',{'task_id':qa.task.id,'report':contract['report'],
        'contract_fingerprint':contract['fingerprint'],'scope':'Assertions frozen outside app source; coverage references are QA proposals.'},update_status=False)
    if contract['suite']['uncovered'] and not contract['suite']['scenarios']:
        store.event(job_id,'AUTONOMOUS_CHECKS_BLOCKED',{'report':contract['report'],'uncovered':contract['suite']['uncovered'],
            'reason':'Some approved criteria need checks outside the current browser protocol. No complete app-check pass is claimed.'})
        return store.read(job_id)
    directory=store.path.parent/'app-checks'/job_id
    def verify(current_root,check_directory,current_job):
        authorize();load_acceptance(ledger,ledger.read(qa.task.id),review)
        report=check_runner(current_root,check_directory,current_job)
        if not report['passed']:return report
        build_path=report['report']
        browser=browser_runner(current_root,directory/uuid4().hex,job_id,contract,report['image'])
        authorize();load_acceptance(ledger,ledger.read(qa.task.id),review)
        failures=[row for row in browser.get('browser',{}).get('results',[]) if row.get('passed') is not True]
        if browser.get('error') or browser.get('cleanup_errors'):
            report['environment_failure']={'stage':'browser_verification','report':browser['report'],
                'error':browser.get('error'),'cleanup_errors':browser.get('cleanup_errors',[])}
        report['checks']['results'].append({'name':'browser_acceptance','exit_code':0 if browser['passed'] else 1,'stopped':None,
            'output':json.dumps({'failures':failures,'error':browser.get('error'),'cleanup_errors':browser['cleanup_errors']},separators=(',',':'))})
        report.update(build_report=build_path,acceptance_report=browser['report'],contract_fingerprint=contract['fingerprint'],
            build_report_sha256=hashlib.sha256(Path(build_path).read_bytes()).hexdigest(),
            acceptance_report_sha256=hashlib.sha256(Path(browser['report']).read_bytes()).hexdigest(),
            review_fingerprint=review['fingerprint'],acceptance_harness_fingerprint=browser['harness_fingerprint'])
        report['cleanup_errors'].extend(browser['cleanup_errors'])
        report['coverage'].update(application_behavior='SELECTED_REQUIREMENTS_BROWSER_CHECKS',
            scenario_structure='PASSED' if contract.get('scenario_quality_version')==1 else 'LEGACY_NOT_CHECKED',
            scenario_review='NO_UNRESOLVED_MODEL_FINDINGS' if contract.get('quality_review') else 'NOT_REVIEWED',
            browser_acceptance='PASSED' if browser['passed'] else 'FAILED',database_restart='NOT_TESTED')
        report['passed']=bool(browser['passed'] and report['source_fingerprint']==browser['source_fingerprint']==source_fingerprint(root)
            and browser['app_image']==report['image'] and browser['contract_fingerprint']==contract['fingerprint'] and not report['cleanup_errors'])
        report['checks']['passed']=report['passed']
        directory.mkdir(parents=True,exist_ok=True);path=directory/(uuid4().hex+'.json');report['report']=str(path.resolve())
        path.write_text(json.dumps(report,indent=2),encoding='utf-8');return report
    owners={file.owner for file in draft.files if file.owner!='qa'}
    if not owners:raise ValueError('Behavior repair requires a source owner')
    worker=SourceAgent(ledger,agents,root,draft,workspace_boundary=boundary,check_runner=verify,authorization=authorize)
    state=child('acceptance_verify',sorted(owners)[0],'Make the approved app pass frozen independent assertions without editing those assertions.',
        {'mode':'repair_build','acceptance_contract':contract['suite']},[Dependency(task_id=qa.task.id,revision=qa.revision)],['isolated_build'])
    if (run_selected or recheck) and state.status=='completed':state=ledger.revise(state,state.task)
    fresh_check=retry_coverage or run_selected or recheck or (resume and not (resource_resume and current_failure_for_repair(state,root,contract)))
    def verify_or_repair(current):
        nonlocal fresh_check
        authorize();load_acceptance(ledger,ledger.read(qa.task.id),review)
        if not current.observations or fresh_check:
            fresh_check=False
            return build_evidence(WorkspaceTools(ledger,current,root,draft,workspace_boundary=boundary,check_runner=verify,authorization=authorize))
        return worker(current)
    reviewer=SeniorReviewer(agents,ledger,owners,context_loader=lambda _: {**context,'acceptance_contract':contract['suite'],
        'runtime_references':runtime_references(draft.database),
        'source_fingerprint':source_fingerprint(root),'current_source':{file.path:safe_path(root,file.path).read_text(encoding='utf-8')
            for file in draft.files if safe_path(root,file.path).is_file()}},capabilities={role:'Edits only owned app source; never frozen acceptance assertions.' for role in owners})
    state=TaskCoordinator(ledger,{role:verify_or_repair for role in owners},reviewer,lambda:source_fingerprint(root),
        owner_router=lambda current:compiler_repair_owner(current,root,{file.path:file.owner for file in draft.files if file.owner in owners},store.path.parent)).run(state.task.id)
    if state.status!='completed':return pause(state)
    authorize();contract=load_acceptance(ledger,ledger.read(qa.task.id),review);fingerprint=source_fingerprint(root)
    checks=state.observations[-1].checks
    if any(check.fingerprint!=fingerprint for check in checks):
        state=ledger.revise(state,state.task)
        return pause(ledger.pause(state,'Source changed after checks'))
    report_path=Path(checks[0].report);result=json.loads(report_path.read_text(encoding='utf-8'))
    if not result['passed'] or result.get('contract_fingerprint')!=contract['fingerprint']:
        raise ValueError('App checks lack current combined acceptance evidence')
    ledger.observe(ledger.read(parent.task.id),Observation(revision=parent.revision,fingerprint=fingerprint,checks=checks))
    partial=bool(contract['suite']['uncovered'])
    store.event(job_id,'AUTONOMOUS_CHECKS_BLOCKED' if partial else 'AUTONOMOUS_APP_CHECKS_PASSED',{'task_id':state.task.id,'qa_task_id':qa.task.id,
        'verification_revision':state.revision,'verification_version':state.version,
        'source_fingerprint':fingerprint,'review_fingerprint':review['fingerprint'],'contract_fingerprint':contract['fingerprint'],
        'report':str(report_path),'report_sha256':hashlib.sha256(report_path.read_bytes()).hexdigest(),
        'coverage':result['coverage'],
        **({'selected_checks_passed':True,'uncovered':contract['suite']['uncovered'],
            'reason':'Supported frozen assertions passed. Other approved criteria remain uncovered; no complete app-check pass is claimed.'} if partial else {}),
        'scope':'Selected requirements-derived browser checks passed; no READY, security, restart-persistence or release claim.'})
    return store.read(job_id)


def evidence_current(record,store,*,workspace_boundary=None,selected_only=False):
    try:
        event=next(e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_APP_CHECKS_PASSED'
            or selected_only and e['status']=='AUTONOMOUS_CHECKS_BLOCKED' and e['payload'].get('selected_checks_passed') is True)
        review=approved_review(record['job_id'],store);ledger=TaskLedger(store,record['job_id'])
        contract=load_acceptance(ledger,ledger.read(event['qa_task_id']),review)
        checked=ledger.read(event['task_id'])
        root=safe_path(Path(workspace_boundary) if workspace_boundary else PROJECT/'workspace',record['job_id'])
        report=Path(event['report']);result=json.loads(report.read_text(encoding='utf-8'))
        browser_path=Path(result['acceptance_report']);browser=json.loads(browser_path.read_text(encoding='utf-8'))
        build_path=Path(result['build_report']);build=json.loads(build_path.read_text(encoding='utf-8'))
        return bool(checked.status=='completed' and checked.revision==event['verification_revision'] and checked.version==event['verification_version']
            and _runtime_unchanged(root) and source_fingerprint(root)==event['source_fingerprint']==result['source_fingerprint']==browser['source_fingerprint']
            and hashlib.sha256(report.read_bytes()).hexdigest()==event['report_sha256'] and result['passed']
            and hashlib.sha256(browser_path.read_bytes()).hexdigest()==result['acceptance_report_sha256'] and passed_report(browser,contract)
            and hashlib.sha256(build_path.read_bytes()).hexdigest()==result['build_report_sha256'] and build['passed']
            and build['source_fingerprint']==result['source_fingerprint'] and build['harness_fingerprint']==build_harness_fingerprint()
            and result['image']==browser['app_image']==build['image']
            and result['contract_fingerprint']==contract['fingerprint']==event['contract_fingerprint']
            and result['acceptance_harness_fingerprint']==harness_fingerprint() and (selected_only or not contract['suite']['uncovered']))
    except (ValueError,OSError,KeyError,TypeError,StopIteration):return False
