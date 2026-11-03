"""A builder proposes owned source edits through the real workspace tool boundary."""
import hashlib
import json
import re
from typing import Annotated,Literal,Union

from pydantic import Field,RootModel,create_model

from forge.autonomous_planning import AppDraft
from forge.check_context import observed_context,summarize_checks
from forge.handoffs import record_handoff
from forge.import_reference import relative_import_reference
from forge.cycle_context import rejected_state_context,failure_obligations
from forge.tasks import CheckEvidence,Envelope,Observation,Task
from forge.workspace import source_fingerprint
from forge.workspace_tools import ReplaceText,WorkspaceTools,WriteFile,file_hash


INSTRUCTION='''You are a ForgeFSD builder subagent. Implement the requested app from the
original user goal, human clarification answers and agent-authored design. Choose suitable
application types and implementation details; use actual preceding source to keep shared
interfaces consistent. You are authorized to edit only the listed owned files.
The original user request and human answers outrank contradictory draft assumptions.
Follow the response tool schema: write_file supplies a complete new file; replace_text
supplies minimal exact old/new text replacements in the selected existing file. Use
actual unique source snippets, not an entire-file copy for a small repair.
Do not concatenate files, emit markdown
fences, leave TODOs, edit tests/dependencies or claim checks passed. Use the supplied
capability inventory rather than assuming packages exist. Prefer simple working code.
Use Next.js App Router, React, TypeScript, Node built-ins and existing CSS. No Tailwind,
extra packages, external fonts/services or browser imports of server database modules.
Interactive hook components need a use client directive as the first module statement,
before imports, never inside a component function. Its exact source syntax is:
'use client';
Keep the quotes and semicolon; bare use client is invalid TypeScript.
Next.js applies app/layout.tsx automatically; pages do not import or render that root layout.
Use import type for
shared TypeScript-only symbols. Keep server-side SQLite behind server actions or API
handlers; honor the app's chosen interfaces rather than inventing unrelated endpoints.
Model source is not executed on the host. Real isolated checks will verify the result.
When actual failures or a senior-review strategy are supplied, correct their underlying
cause while preserving the original behavior and other files' interfaces. Do not replace
the app with a template, remove required behavior or weaken tests. Use raw source
strings in the tool fields, not a second encoded JSON string. In repair mode, implement the QA
repair_focus steps in the selected file. Repeating the current file unchanged is not
a correction. Fix actual reported causes, not unrelated formatting or cosmetic changes.'''


class RepairFocus(Envelope):
    file: str
    cause: str = Field(min_length=1,max_length=700)
    changes: list[str] = Field(min_length=1,max_length=6)


class SourceTarget(Envelope):
    path: str
    change: str = Field(min_length=1,max_length=500,description='Concise intended correction, not private reasoning.')


SOURCE_TEXT_INSTRUCTION='''Implement or repair the one file named by write_target.
Return its COMPLETE raw source contents only. Do not return JSON, tool fields, patches,
explanation or multiple files. A single source fence is accepted. Complete every
function and JSX element; do not copy an unfinished file ending from the current source.
Preserve the original user request, clarification answers, review feedback and frozen
acceptance assertions. Choose app-owned types and implementation details yourself.
Use actual other files' exports and props, the supported runtime references and real
compiler/browser evidence. repair_focus, selected_change and fresh_review are advisory;
correct their hypothesis when the actual source/evidence disagrees. Never weaken tests,
add dependencies, replace the requested app with a placeholder or claim execution.
Use quoted 'use client'; before imports for interactive React modules. HTTP route and
SQLite modules remain server-only. Client components use fetch rather than importing
route handlers. Resolve imports from the selected file's actual directory. Preserve
server metadata in server modules. No new packages or external services are available.
This response supplies file contents only; the controller enforces ownership and hashes.'''
SOURCE_TEXT_INSTRUCTION+=''' When cycle_repair_actions is supplied, implement every
listed correction together in this file. rejected_state describes a historically failed
candidate, not the current file; avoid restoring it. A directive-only edit cannot fix
a separate missing-import or HTTP boundary failure. Verify proposed actions against
actual source and runtime facts rather than copying a wrong plan.'''


FOCUS_INSTRUCTION='''You are the QA diagnosis subagent. Inspect the actual latest verification
failure and current app source. Choose ONE authorized file to correct next and give
concrete source-level changes that address its reported causes. Prioritize actual
errors, not formatting. State what must change, not only that an error exists. Use
actual paths and symbols from the supplied files. Preserve the user requirements,
validation and interfaces. Do not propose new dependencies, weaken tests, invent a
successful result or repeat an unchanged edit. Other files can be addressed in later
iterations after this focused correction is checked. Ground the cause in the exact
diagnostic line, column and expression_at_column; do not guess from a nearby function
name. Re-evaluate prior diagnoses when they disagree with the actual location.'''
FOCUS_INSTRUCTION+=''' Select the module that owns the correction, not merely the page
where a symptom appears. Each proposed change must be implementable in that file.
For missing document metadata with a client page, inspect the server layout. Your
target is advisory; the builder may correct another file within its existing ownership.'''
FOCUS_INSTRUCTION+=''' Read structured browser failure_context before interpreting a
timeout. kind=missing_target with match_count=0 means the requested semantic target
was absent. Compare the accessibility snapshot and source markup to the frozen target.
Do not guess slow performance, increase immutable test timeouts, or change numeric
state types merely because a UI target is missing. Propose an owned app-source fix.'''
FOCUS_INSTRUCTION+=''' For kind=text_mismatch, compare actual_text with expected and
inspect the rendered JSX for that target. An extra label or prefix is a presentation
mismatch; it does not by itself demonstrate broken state arithmetic or input handlers.
kind=value_mismatch refers to an input's value, not its surrounding visible text.'''


REPAIR_INSTRUCTION='''Repair the selected existing file so the supplied real compiler,
build or browser acceptance failures are resolved. Return only a tool request matching the schema.
The compiler output and actual source are evidence. repair_focus is an advisory
hypothesis from another model: independently verify it and correct it if wrong.
You may select ANY allowed target owned by your role, even if QA selected another file.
Choose the file that actually owns the correction. Never repeat a no-op in the wrong
module merely to follow QA's recommendation.
fresh_review, when present, was requested for this exact source/evidence snapshot.
Consider its strategy alongside the compiler and source; it is advisory, not proof.
For browser missing_target facts, align the app's accessible markup/control with the
frozen target while preserving behavior. A zero-match timeout is not a reason to edit
tests, increase waits, or change otherwise-correct numeric state into strings.
Read the selected file and other files' actual exports and props before editing.
Resolve relative imports from the directory of the importing file, not the app root.
Next.js supplies app/layout.tsx automatically; pages must not invent a layout import.
Hooks and browser event handlers require a use client component boundary. The
directive must be the first module statement, before imports, never inside a function.
The exact source statement is 'use client'; including the quotes and semicolon.
Do not emit bare use client or an escaped JSON string inside the source file.
If an invalid unquoted directive caused a parse error, quote it rather than deleting
the client boundary still needed by hooks. Client modules cannot export server metadata;
keep metadata in the server layout or separate interactive code from server metadata.
Choose write_file for a complete corrected file, or replace_text for small local
edits. Prefer a complete file when changing component structure or several related
declarations; do not insert a whole component into an import-line replacement.
For replace_text each old snippet must occur exactly once, and new text must differ.
For write_file return the entire corrected file once, with no duplicate declarations.
Preserve the original user requirements and existing cross-file interfaces. Do not
remove required behavior, weaken tests, add dependencies or claim a successful check.
Use actual available dependencies and raw source strings, without markdown fences.
Fix the cause at the diagnostic location; do not just restate the error.'''


def diagnostic_context(failure,source):
    if not failure:return []
    output='\n'.join(check['summary'] for check in failure.get('checks',[]))
    locations=[]
    for path,file in source.items():
        pattern=re.escape(path)+r'\((\d+),(\d+)\): (?:error )?([A-Z][A-Z0-9_]+): ([^\r\n]+)'
        lines=file['content'].splitlines()
        for match in re.finditer(pattern,output):
            line,column=int(match[1]),int(match[2])
            if 1<=line<=len(lines):
                locations.append({'file':path,'line':line,'column':column,'code':match[3],'message':match[4],
                    'line_text':lines[line-1],'expression_at_column':lines[line-1][column-1:column+100],
                    'source_excerpt':[f'{i+1}: {lines[i]}' for i in range(max(0,line-3),min(len(lines),line+2))]})
    return locations


class SourceAgent:
    def __init__(self,ledger,agents,root,draft,*,workspace_boundary=None,check_runner=None,authorization=None):
        self.ledger=ledger;self.agents=agents;self.root=root;self.draft=AppDraft.model_validate(draft)
        self.tool_options={'workspace_boundary':workspace_boundary,'authorization':authorization}
        if check_runner is not None:self.tool_options['check_runner']=check_runner

    def __call__(self,state):
        tools=WorkspaceTools(self.ledger,state,self.root,self.draft,**self.tool_options)
        if not state.task.inputs.get('original_request'):raise ValueError('Source tasks require the original user request, not only an isolated file instruction')
        repairing=state.task.inputs.get('mode')=='repair_build'
        owned=[path for path,owner in tools.owners.items() if owner==state.task.owner]
        targets=owned if repairing else [state.task.inputs['file']]
        if not targets or any(path not in owned for path in targets):raise ValueError('Source task has no authorized target files')
        source={};variants=[];before=source_fingerprint(tools.root)
        # Read complete current files and the platform scaffold; never synthesize context.
        for path in dict.fromkeys([*targets,*tools.owners,'app/layout.tsx','app/globals.css','tsconfig.json','next.config.ts']):
            result=tools.execute({'tool':'read_file','path':path})
            if not result['ok']:raise ValueError(result['error'])
            if result['data']['exists']:source[path]=result['data']
        fingerprint=source_fingerprint(tools.root)
        if fingerprint!=before:raise ValueError('Workspace changed while context was being read; retrieve a fresh snapshot')
        capabilities=tools.describe();capabilities.pop('schema')  # Keep tool-envelope schemas out of source-body context.
        if state.task.inputs.get('acceptance_contract'):
            capabilities['checks_available'].append('browser_acceptance')
            capabilities['frozen_browser_contract']='Executed separately from app source; builders cannot modify its assertions.'
        data={'task':{'goal':state.task.goal,'owner':state.task.owner,'revision':state.revision},
            'original_request':state.task.inputs.get('original_request',''),
            'human_clarifications':state.task.inputs.get('human_clarifications',[]),
            'human_review_feedback':state.task.inputs.get('human_review_feedback',[]),
            'acceptance_contract':state.task.inputs.get('acceptance_contract'),
            'app_design':self.draft.model_dump(),'capabilities':capabilities,
            'source':source,'workspace_fingerprint':fingerprint,'allowed_targets':targets,
            'recent_failures':[o.model_dump() for o in state.observations if o.revision==state.revision][-2:],
            'latest_build_failure':next((o.model_dump() for o in reversed(state.observations) if o.revision==state.revision
                and any(c.check=='isolated_build' and c.exit_code!=0 for c in o.checks)),None),
            'attempt':state.actions_used,'stalled_attempts':state.no_progress,'repair_mode':repairing,
            'previous_build':state.task.inputs.get('build_failure'),
            'recovery_strategy':state.recovery.model_dump() if state.recovery and state.reviewed_observations==len(state.observations) else None}
        if len(json.dumps(data,separators=(',',':')))>22000:
            raise ValueError('Complete source/interface context exceeds this worker budget; split the task instead of silently dropping contracts')
        if getattr(self.agents,'trace_directory',None) is None:
            self.agents.trace_directory=self.ledger.store.path.parent/'model-calls'/self.ledger.job_id
        if repairing:
            if not data['latest_build_failure']:raise ValueError('Repair requires actual build failure evidence, not a guessed correction')
            if data['latest_build_failure']['fingerprint']!=fingerprint:
                # Locations from another source snapshot cannot justify an edit.
                # Recheck first; the coordinator will record this fresh evidence.
                return build_evidence(tools)
            observed=next(o for o in reversed(state.observations) if o.revision==state.revision
                and any(c.check=='isolated_build' and c.exit_code!=0 for c in o.checks))
            data['latest_build_failure']=observed_context(observed,self.ledger.store.path.parent)
            data['diagnostic_locations']=diagnostic_context(data['latest_build_failure'],source)
            for location in data['diagnostic_locations']:
                if location['code']=='TS2307':
                    reference=relative_import_reference(location['file'],location['message'],source)
                    if reference:location['module_reference']=reference
            # A prior diagnosis is a hypothesis, not compiler evidence. Replaying it
            # beside each new diagnosis anchored the model on incorrect causes.
            data['last_tool_error']=state.observations[-1].error if state.observations else ''
            data['repair_cycle_detected']='Repair cycle rejected:' in data['last_tool_error']
            data['rejected_state']=rejected_state_context(state,self.ledger.store.path.parent)
            data['failure_obligations']=failure_obligations(data['diagnostic_locations'],data['rejected_state'],source)
            data['framework_reference']={
                'client_directive_source':"'use client';\n",
                'client_boundary':'Place the quoted string literal before imports when using client hooks or browser handlers.',
                'server_metadata':'Client modules cannot export metadata/generateMetadata; keep these in server modules.',
                'root_layout':'Next.js applies the root layout automatically; do not import it into a page.'}
            data['replace_rejected_patch']=bool(data['last_tool_error']) and any(
                message in data['last_tool_error'] for message in
                ('Patch snippet','Patch edit','Proposed repair is unchanged source','Repair cycle rejected:'))
            if data['replace_rejected_patch']:
                data['edit_guidance']='The preceding local patch failed. Return one complete corrected file with write_file instead of repeating a patch.'
            for key in ('recent_failures','recovery_strategy','previous_build'):
                data.pop(key,None)
            if state.recovery and state.reviewed_observations==len(state.observations):
                data['fresh_review']={'source_fingerprint':fingerprint,'strategy':state.recovery.model_dump(),
                    'scope':'Advisory strategy for this observation set only; verify it against current source and checks.'}
            focus=self._focus(state,data,targets)
            # QA is another model invocation: inputs may have expired while it ran.
            # Revalidate before forwarding its diagnosis and source to the builder.
            tools.describe()
            if source_fingerprint(tools.root)!=fingerprint:return build_evidence(tools)
            data['repair_focus']=focus.model_dump()
            # Repair is a source/debugging task, not another architecture proposal.
            # Retain requirements and complete interfaces, but avoid asking the
            # builder to follow contradictory assumptions from the original draft.
            data['acceptance_criteria']=self.draft.acceptance_criteria
            data.pop('app_design')
            if len(json.dumps(data,separators=(',',':')))>22000:raise ValueError('Focused repair context exceeds the complete-source budget; split the task')
        if callable(getattr(self.agents,'generate_source',None)):
            proposal=self._raw_proposal(state,data,targets,tools,fingerprint,repairing)
        else:
            for index,path in enumerate(targets):
                digest=file_hash(tools.root/path)
                fields={'path':(Literal[path],...),'expected_sha256':(Literal[digest],...),
                    'expected_workspace_fingerprint':(Literal[fingerprint],...)}
                write=create_model(f'OwnedWrite{index}',__base__=WriteFile,
                    require_change=(Literal[repairing],...),**fields)
                if repairing and digest is not None and not data['replace_rejected_patch']:
                    patch=create_model(f'OwnedPatch{index}',__base__=ReplaceText,**fields)
                    variants.append(Annotated[Union[write,patch],Field(discriminator='tool')])
                else:variants.append(write)
            choice=variants[0] if len(variants)==1 else Annotated[Union[tuple(variants)],Field(discriminator='path')]
            schema=create_model('SourceEdit',__base__=RootModel[choice])
            record_handoff(self.ledger.store,self.ledger.job_id,'qa' if repairing else 'coordinator',state.task.owner,
                'Propose an owned source edit using the agent design, actual files and available tools.',
                data,agents=self.agents,task_id=state.task.id,parent_task_id=state.task.parent_id)
            previous=getattr(self.agents,'activity',None)
            try:
                self.agents.activity=lambda status,payload:self.ledger.store.event(self.ledger.job_id,status,payload,update_status=False)
                proposal=self.agents.generate(schema,REPAIR_INSTRUCTION if repairing else INSTRUCTION,data,coding=True).root
            finally:self.agents.activity=previous
        outcome=tools.execute(proposal.model_dump(),initiator='model',
            proposal_call_id=getattr(self.agents,'last_call_identity',{}).get('call_id'))
        if not outcome['ok']:raise ValueError(outcome['error'])
        if not repairing:
            return [CheckEvidence(check='source_written',exit_code=0,fingerprint=outcome['data']['sha256'],
                report=outcome['report'],summary='Model-proposed source saved through ownership/hash checks; compilation and behavior are not implied.')]
        return build_evidence(tools)

    def _raw_proposal(self,state,data,targets,tools,fingerprint,repairing):
        previous=getattr(self.agents,'activity',None);target=targets[0];change=None
        try:
            self.agents.activity=lambda status,payload:self.ledger.store.event(self.ledger.job_id,status,payload,update_status=False)
            if repairing and len(targets)>1:
                schema=create_model('SourceTarget',__base__=SourceTarget,path=(Literal[tuple(targets)],...))
                record_handoff(self.ledger.store,self.ledger.job_id,'qa',state.task.owner,
                    'Select an owned repair target from actual source and check evidence.',data,
                    agents=self.agents,task_id=state.task.id,parent_task_id=state.task.parent_id)
                selected=schema.model_validate(self.agents.generate(schema,
                    'Choose the owned file that needs correction. QA focus is advisory; use actual evidence. Return only target metadata, not source or an execution claim.',data,coding=True))
                target=selected.path;change=selected.change
            tools.describe()
            if source_fingerprint(tools.root)!=fingerprint:raise ValueError('Workspace context changed during target selection; retrieve fresh source')
            context={**data,'write_target':target,'file':target,'selected_change':change,'source_transport':'raw_complete_file'}
            context.pop('replace_rejected_patch',None);context.pop('edit_guidance',None)
            if repairing and data.get('rejected_state'):
                obligations=[row for row in data['failure_obligations'] if row['file']==target]
                if obligations:
                    fields={row['id']:(str,Field(min_length=1,max_length=500,
                        description=f"Concrete correction for {row['code']}: {row['message']}")) for row in obligations}
                    schema=create_model('CycleRepairActions',__base__=Envelope,**fields)
                    record_handoff(self.ledger.store,self.ledger.job_id,'coordinator',state.task.owner,
                        'Plan one correction per current or rejected-state failure before generating replacement source.',context,
                        agents=self.agents,task_id=state.task.id,parent_task_id=state.task.parent_id)
                    actions=self.agents.generate(schema,
                        'Plan concrete corrections for EVERY listed failure in write_target. Current and rejected-candidate failures must be addressed together to escape a cycle. Use actual source and module references. Keep hooks client-side and HTTP/database modules server-side. Return concise correction actions, not source or a pass claim.',context,coding=True)
                    context['cycle_repair_actions']=schema.model_validate(actions).model_dump()
                    # Ordinary diagnoses selected the failed loop; do not anchor the
                    # new body on those hypotheses after the explicit recovery plan.
                    for key in ('repair_focus','fresh_review','selected_change'):context.pop(key,None)
                    tools.describe()
                    if source_fingerprint(tools.root)!=fingerprint:raise ValueError('Workspace context changed during cycle planning; retrieve fresh source')
            record_handoff(self.ledger.store,self.ledger.job_id,'qa' if repairing else 'coordinator',state.task.owner,
                'Generate one complete source body for the chosen owned file; path and hashes remain controller-bound.',context,
                agents=self.agents,task_id=state.task.id,parent_task_id=state.task.parent_id)
            content=self.agents.generate_source(SOURCE_TEXT_INSTRUCTION,context)
            old=data['source'].get(target)
            return WriteFile(tool='write_file',path=target,content=content,expected_sha256=old['sha256'] if old else None,
                expected_workspace_fingerprint=fingerprint,require_change=repairing)
        finally:self.agents.activity=previous

    def _focus(self,state,data,targets):
        schema=create_model('RepairFocus',__base__=RepairFocus,file=(Literal[tuple(targets)],...))
        child=self.ledger.create(Task(parent_id=state.task.id,owner='qa',
            goal='Select a concrete source correction from actual build evidence.',
            inputs={'failed_task':state.task.id,'input_revision':state.revision},required_checks=['repair_focus']),action_limit=1)
        child=self.ledger.reserve_action(self.ledger.start(child),'qa')
        previous_context=getattr(self.agents,'invocation_context',{});previous_activity=getattr(self.agents,'activity',None)
        focus=None;error=''
        try:
            record_handoff(self.ledger.store,self.ledger.job_id,state.task.owner,'qa',
                'Diagnose the actual failure and delegate one concrete repair target to the builder.',data,
                agents=self.agents,task_id=child.task.id,parent_task_id=state.task.id)
            self.agents.activity=lambda status,payload:self.ledger.store.event(self.ledger.job_id,status,payload,update_status=False)
            focus=schema.model_validate(self.agents.generate(schema,FOCUS_INSTRUCTION,data,coding=True))
        except Exception as exc:error=f'{type(exc).__name__}: {exc}'[:2000]
        finally:self.agents.invocation_context=previous_context;self.agents.activity=previous_activity
        directory=self.ledger.store.path.parent/'repair-focus'/self.ledger.job_id;directory.mkdir(parents=True,exist_ok=True)
        report=directory/(child.task.id+'.json')
        report.write_text(json.dumps({'focus':focus.model_dump() if focus else None,'error':error,
            'source_fingerprint':data['workspace_fingerprint'],'scope':'Diagnosis proposal only; correction effectiveness requires execution.'},indent=2),encoding='utf-8',newline='\n')
        fingerprint=hashlib.sha256(report.read_bytes()).hexdigest()
        child=self.ledger.observe(child,Observation(revision=child.revision,fingerprint=fingerprint,
            checks=[CheckEvidence(check='repair_focus',exit_code=int(bool(error)),fingerprint=fingerprint,report=str(report.resolve()),summary=error or 'Focused repair proposal validated; no app checks passed by assertion.')]))
        if error:
            self.ledger.pause(child,'Diagnosis needs correction; parent retains evidence.')
            raise ValueError(error)
        return focus


def build_evidence(tools):
    outcome=tools.execute({'tool':'check_build'})
    if not outcome['ok']:raise ValueError(outcome['error'])
    data=outcome['data']
    summary=summarize_checks(data['checks'],data.get('source_diagnostics',[]),data.get('error'))
    return [CheckEvidence(check='isolated_build',exit_code=0 if data['passed'] else 1,
        fingerprint=data['source_fingerprint'],report=data['report'],
        summary=(summary or str(data.get('error') or 'Build report was incomplete'))[:2000])]
