"""Agent-authored app designs. Validate the workspace protocol, not business types."""
import hashlib
import json
from pathlib import Path,PurePosixPath
from typing import Literal

from pydantic import Field

from forge.coordinator import TaskCoordinator
from forge.handoffs import record_handoff
from forge.schemas import ApplicationRequest
from forge.senior_review import SeniorReviewer
from forge.contracts import IntakeDecision
from forge.planning import INTAKE_INSTRUCTION,HELP_RESPONSES
from forge.tasks import CheckEvidence,Dependency,Envelope,Task,TaskLedger
from forge.workspace import safe_path,is_test_source


class DraftFile(Envelope):
    path: str = Field(min_length=1,max_length=200)
    owner: Literal['builder','frontend','backend','qa']
    purpose: str = Field(min_length=1,max_length=600)


class AppDraft(Envelope):
    title: str = Field(min_length=1,max_length=160)
    design: str = Field(min_length=1,max_length=12000,description='Your app architecture, behavior, state ownership and shared interfaces; choose app-specific types and structure freely.')
    database: Literal['none','sqlite']
    files: list[DraftFile] = Field(max_length=20)
    acceptance_criteria: list[str] = Field(min_length=1,max_length=20)
    test_strategy: str = Field(min_length=1,max_length=3000)
    assumptions: list[str] = Field(default_factory=list,max_length=8)


INSTRUCTION='''You are ForgeFSD's planner subagent. Independently design the app requested
by the user. Choose suitable business types, data model, routes if needed, project
structure, UI behavior and state ownership. Explain interfaces shared between tasks.
The design is an app-owned agreement that can be revised with affected agents.
Do not fit requests into a task-manager template or invent unnecessary architecture.
Use the supplied Next.js App Router/TypeScript, React and Node 24 base with plain CSS
or inline styles. Existing dependencies are fixed for this POC; no Tailwind, extra
packages, authentication, payments or external services. Local SQLite is available
when persistence is needed; database=none is valid. A landing page or client-side
tool does not need an API, backend task or database merely to satisfy a template.
Use app/page.tsx as the home entry; app/layout.tsx and app/globals.css are already
seeded and may be changed if useful. Other app/components/lib/public/styles/tests
files can be chosen within the supplied manifest rules. Package/configuration files
remain controller-owned. Assign files to builder, frontend, backend or qa as useful;
one builder is enough for a small app. Define expected behavior and applicable tests
from the request, not invented implementation results. Assumptions cannot waive
requirements. Requirements intake has already established the supported scope. Respect
the supplied clarification answers and choose sensible defaults for remaining design
choices. Do not reopen optional scope questions or ask the user to design the internals.
This is a proposal for human review; never claim that an app was built or tests passed.
Return the complete design, not only a correction. If previous evidence or senior
review is supplied, use it to change the unsuccessful approach.'''


def manifest_issues(draft,root):
    issues=[];seen=set()
    for file in draft.files:
        try:safe_path(root,file.path)
        except ValueError as exc:issues.append(f'{file.path}: {exc}');continue
        path=PurePosixPath(file.path)
        if path.parts[0] not in {'app','components','lib','public','styles','tests'}:
            issues.append(f'{file.path}: outside application source roots; package/configuration files are controller-owned')
        if path.suffix not in {'.ts','.tsx','.css','.json','.svg','.sql'} or any(p.startswith('.') or p=='node_modules' for p in path.parts):
            issues.append(f'{file.path}: unsupported or protected source path')
        if file.path.casefold() in seen:issues.append(f'{file.path}: duplicate file or conflicting ownership')
        seen.add(file.path.casefold())
        if is_test_source(file.path) and file.owner!='qa':issues.append(f'{file.path}: independent test files belong to QA')
    if 'app/page.tsx' not in {f.path for f in draft.files}:
        issues.append('The Next.js runtime needs the home entry app/page.tsx; no business layout or API is prescribed.')
    return issues


def draft_task(store,job_id,description,*,action_limit=8,parent=None,inputs=None):
    ledger=TaskLedger(store,job_id)
    state=ledger.create(Task(owner='planner',goal='Propose a reviewable app design from the original request and clarification answers.',
        parent_id=parent.task.id if parent else None,
        dependencies=[Dependency(task_id=parent.task.id,revision=parent.revision)] if parent else [],
        inputs=inputs or {'original_request':description},required_checks=['draft_schema','workspace_manifest']),action_limit=action_limit)
    return ledger,state


def continue_draft(ledger,task_id,agents):
    directory=ledger.store.path.parent/'autonomous-plans'/ledger.job_id
    directory.mkdir(parents=True,exist_ok=True);candidate=directory/'candidate.json'
    def fingerprint():return hashlib.sha256(candidate.read_bytes() if candidate.exists() else b'').hexdigest()
    def context(state):
        return {**state.task.inputs,'latest_proposal':json.loads(candidate.read_text(encoding='utf-8')) if candidate.exists() else None,
            'recent_failures':[o.model_dump() for o in state.observations if o.revision==state.revision][-2:],
            'recovery_strategy':state.recovery.model_dump() if state.recovery else None}
    if getattr(agents,'trace_directory',None) is None:
        agents.trace_directory=ledger.store.path.parent/'model-calls'/ledger.job_id
    def planner(state):
        data=context(state)
        record_handoff(ledger.store,ledger.job_id,'coordinator','planner',
            'Choose the application design and shared interfaces from the user goal; use observed feedback to revise it.',
            data,agents=agents,task_id=state.task.id,parent_task_id=state.task.parent_id)
        previous_activity=getattr(agents,'activity',None)
        try:
            agents.activity=lambda status,payload:ledger.store.event(ledger.job_id,status,payload,update_status=False)
            proposed=AppDraft.model_validate(agents.generate(AppDraft,INSTRUCTION,data,coding=True))
            candidate.write_text(proposed.model_dump_json(indent=2),encoding='utf-8',newline='\n')
            snapshot=directory/f'draft-{state.actions_used}.json';snapshot.write_bytes(candidate.read_bytes())
        finally:agents.activity=previous_activity
        issues=manifest_issues(proposed,directory/'unexecuted-workspace')
        report=directory/f'check-{state.actions_used}.json'
        report.write_text(json.dumps({'draft_sha256':fingerprint(),'draft_snapshot':str(snapshot.resolve()),'issues':issues,
            'scope':'Proposal structure and workspace manifest only; business completeness and execution remain unverified.'},indent=2),encoding='utf-8')
        return [CheckEvidence(check=name,exit_code=int(bool(issues)) if name=='workspace_manifest' else 0,
            fingerprint=fingerprint(),report=str(report.resolve()),summary='; '.join(issues) if issues else 'Draft protocol validated; app execution not performed.')
            for name in ['draft_schema','workspace_manifest']]
    reviewer=SeniorReviewer(agents,ledger,{'planner'},context_loader=context,
        capabilities={'planner':'Owns and can revise the complete app design, source manifest and shared interfaces while preserving the user goal.'})
    state=TaskCoordinator(ledger,{'planner':planner},reviewer,fingerprint).run(task_id)
    if state.status=='completed':
        draft=AppDraft.model_validate_json(candidate.read_text(encoding='utf-8'))
        ledger.store.event(ledger.job_id,'AUTONOMOUS_DRAFT_READY',{'title':draft.title,'task_id':task_id,'revision':state.revision,
            'report':str(candidate.resolve()),'draft_sha256':fingerprint(),'approval':'NOT_APPROVED','app_execution':'NOT_RUN'})
    else:
        ledger.store.event(ledger.job_id,'AUTONOMOUS_PAUSED',{'task_id':task_id,'reason':state.pause_reason or state.status,
            'revision':state.revision,'app_execution':'NOT_RUN'})
    return ledger.store.read(ledger.job_id)


def plan_app(description,agents,store,*,action_limit=8):
    request=ApplicationRequest(description=description,model=agents.model_name)
    job=store.create(request.model_dump());ledger=TaskLedger(store,job)
    intake=ledger.create(Task(owner='requirements',goal='Determine whether the user request is understood, needs business clarification or is outside scope.',
        inputs={'original_request':description},required_checks=['intake_schema']),action_limit=action_limit)
    return continue_intake(ledger,intake.task.id,agents)


def continue_intake(ledger,task_id,agents):
    directory=ledger.store.path.parent/'autonomous-plans'/ledger.job_id;directory.mkdir(parents=True,exist_ok=True)
    route=directory/'intake.json'
    def fingerprint():return hashlib.sha256(route.read_bytes() if route.exists() else b'').hexdigest()
    def worker(state):
        data={'application_request':state.task.inputs['original_request'],
              'human_clarifications':state.task.inputs.get('human_clarifications',[])}
        if getattr(agents,'trace_directory',None) is None:agents.trace_directory=ledger.store.path.parent/'model-calls'/ledger.job_id
        record_handoff(ledger.store,ledger.job_id,'coordinator','requirements',
            'Establish the business scope before architecture; optional implementation choices are delegated to the planner.',
            data,agents=agents,task_id=state.task.id,parent_task_id=state.task.parent_id)
        previous_activity=getattr(agents,'activity',None)
        try:
            agents.activity=lambda status,payload:ledger.store.event(ledger.job_id,status,payload,update_status=False)
            decision=agents.generate(IntakeDecision,INTAKE_INSTRUCTION,data)
        finally:agents.activity=previous_activity
        route.write_text(decision.model_dump_json(indent=2),encoding='utf-8',newline='\n')
        snapshot=directory/f'intake-{state.actions_used}.json';snapshot.write_bytes(route.read_bytes())
        return [CheckEvidence(check='intake_schema',exit_code=0,fingerprint=fingerprint(),report=str(snapshot.resolve()),
            summary='Intent proposal validated; no application correctness is established.')]
    reviewer=SeniorReviewer(agents,ledger,{'requirements'},capabilities={'requirements':'Owns request classification and blocking business clarification; delegates understood app design.'})
    state=TaskCoordinator(ledger,{'requirements':worker},reviewer,fingerprint).run(task_id)
    if state.status!='completed':
        ledger.store.event(ledger.job_id,'AUTONOMOUS_PAUSED',{'task_id':task_id,'stage':'intake','reason':state.pause_reason or state.status})
        return ledger.store.read(ledger.job_id)
    decision=IntakeDecision.model_validate_json(route.read_text(encoding='utf-8')).root
    if decision.intent=='build':
        _,draft=draft_task(ledger.store,ledger.job_id,state.task.inputs['original_request'],action_limit=state.action_limit,parent=state,inputs=state.task.inputs)
        return continue_draft(ledger,draft.task.id,agents)
    if decision.intent=='clarify':
        ledger.store.event(ledger.job_id,'AUTONOMOUS_INPUT_NEEDED',{'task_id':task_id,'stage':'intake','questions':decision.questions,
            'reason':decision.blocking_reason,'report':str(route.resolve()),'approval':'NOT_APPROVED','app_execution':'NOT_RUN'})
    else:
        message=HELP_RESPONSES[decision.topic] if decision.intent=='help' else 'ForgeFSD builds small web apps; this request is outside that workflow. No app was generated.'
        ledger.store.event(ledger.job_id,'REQUEST_ANSWERED',{'intent':decision.intent,'message':message})
    return ledger.store.read(ledger.job_id)


def answer_intake(job_id,answers,agents,store):
    record=store.read(job_id)
    if record['status']!='AUTONOMOUS_INPUT_NEEDED':raise ValueError('No autonomous intake question is pending')
    pending=next(e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_INPUT_NEEDED')
    if pending.get('stage')!='intake':raise ValueError('This question does not belong to requirements intake')
    questions=pending['questions']
    if len(answers)!=len(questions) or any(not isinstance(a,str) or not a.strip() or len(a)>1000 for a in answers):
        raise ValueError('Supply one nonempty answer of at most 1000 characters per question')
    ledger=TaskLedger(store,job_id);state=ledger.read(pending['task_id'])
    inputs={**state.task.inputs,'human_clarifications':[
        *state.task.inputs.get('human_clarifications',[]),
        *[{'question':q,'answer':a} for q,a in zip(questions,answers,strict=True)]]}
    revised=ledger.revise(state,state.task.model_copy(update={'inputs':inputs}))
    return continue_intake(ledger,revised.task.id,agents)
