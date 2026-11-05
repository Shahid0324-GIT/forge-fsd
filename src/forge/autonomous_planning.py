"""Agent-authored app designs. Validate the workspace protocol, not business types."""
import hashlib
import json
from pathlib import Path,PurePosixPath
from typing import Literal

from pydantic import Field

from forge.coordinator import TaskCoordinator
from forge.handoffs import record_handoff
from forge.intake_review import review_clarification
from forge.schemas import ApplicationRequest
from forge.senior_review import SeniorReviewer
from forge.contracts import IntakeDecision
from forge.planning import INTAKE_INSTRUCTION,HELP_RESPONSES
from forge.tasks import CheckEvidence,Dependency,Envelope,Task,TaskLedger
from forge.workspace import safe_path,is_test_source,source_fingerprint
from forge.browser_capabilities import browser_capabilities
from forge.design_interfaces import SharedInterface,interface_issues
from forge.implementation_review import review_design,prior_review


TEMPLATE=Path(__file__).resolve().parents[2]/'templates/task-app'


class DraftFile(Envelope):
    path: str = Field(min_length=1,max_length=200)
    owner: Literal['builder','frontend','backend','qa']
    purpose: str = Field(min_length=1,max_length=600)


class AppDraft(Envelope):
    title: str = Field(min_length=1,max_length=160)
    design: str = Field(min_length=1,max_length=12000,description='Your app architecture, behavior, state ownership and shared interfaces; choose app-specific types and structure freely.')
    database: Literal['none','sqlite'] = Field(description='Server database choice only. none permits browser storage when requested; it does not mean state must disappear on reload. Choose the storage lifecycle from the actual user request.')
    files: list[DraftFile] = Field(max_length=20)
    interfaces: list[SharedInterface] = Field(default_factory=list,max_length=20)
    acceptance_criteria: list[str] = Field(min_length=1,max_length=20)
    test_strategy: str = Field(min_length=1,max_length=3000)
    assumptions: list[str] = Field(default_factory=list,max_length=8)


INSTRUCTION='''You are ForgeFSD's planner subagent. Independently design the app requested
by the user. Choose suitable business types, data model, routes if needed, project
structure, UI behavior and state ownership. Explain interfaces shared between tasks.
The design is an app-owned agreement that can be revised with affected agents.
Declare interfaces for shared modules/components and browser/server calls using
your chosen provider and consumer files. Agree on exact exports/props/types or
HTTP/action request-response signatures before delegating implementation. These
are agent decisions; never ask the user to supply them. Multiple owners require
an explicit shared-interface agreement. Providers will be implemented before
their consumers. Avoid dependency cycles by choosing suitable shared modules.
Do not fit requests into a task-manager template or invent unnecessary architecture.
Acceptance criteria describe the requested app's observable behavior. Keep fixed
platform/tool constraints (installed packages, workspace isolation, SQLITE_PATH and
the controller's execution policy) in the design or assumptions; do not invent them
as extra user-facing feature criteria. Preserve explicitly requested behavior and
persistence requirements, including validation and reload behavior.
Use the supplied Next.js App Router/TypeScript, React and Node 24 base with plain CSS
or inline styles. Existing dependencies are fixed for this POC; no Tailwind, extra
packages, authentication, payments or external services. Local SQLite is available
when server-side persistence is needed; browser storage can satisfy appropriate
browser-only persistence. database=none means no server database, not no saved data.
A landing page or client-side
tool does not need an API, backend task or database merely to satisfy a template.
Use app/page.tsx as the home entry; app/layout.tsx and app/globals.css are already
seeded and may be changed if useful. Other app/components/lib/public/styles/tests
files can be chosen within the supplied manifest rules. Package/configuration files
remain controller-owned. Assign application files to builder, frontend or backend;
QA owns the controller's independent browser contract outside the workspace, not
application source. Do not add test files to this manifest: no unit-test framework
or arbitrary test-file runner is installed. Describe behavior checks in test_strategy;
the controller compiles and runs the independently frozen browser scenarios.
one builder is enough for a small app. Define expected behavior and applicable tests
from the request, not invented implementation results. Assumptions cannot waive
requirements. Acceptance criteria express requested functionality and explicit constraints;
do not promote your optional styling/placement choices into new acceptance requirements.
Requirements intake has already established the supported scope. Respect
the actual requested state lifetime: reload persistence, session lifetime and no
persistence are different requirements. Do not copy a hypothetical example or a
platform constraint into product behavior. Follow the supplied clarification
answers and choose sensible defaults for remaining design
choices. Do not reopen optional scope questions or ask the user to design the internals.
Apply human_review_feedback as requirements updates without relaxing platform policy.
Use runtime_capabilities as the actual platform facts. Do not assume test frameworks
or external services are installed. If you choose HTTP handlers, use the runtime's
route-handler convention; a source helper is not automatically an HTTP endpoint.
Prefer the simplest design that satisfies the request; a backend is optional.
This is a proposal for human review; never claim that an app was built or tests passed.
Return the complete design, not only a correction. If previous evidence or senior
review is supplied, use it to change the unsuccessful approach.
implementation_findings are an internal engineering review: resolve them yourself
against the original request and its supplied reference evidence. Do not adopt an
unsupported critique as a new user requirement. Preserve business scope.
invalid_proposal is your latest rejected response;
correct its reported schema errors instead of starting over or asking the user.
verification_capabilities describes the checks actually available, not the desired
feature set. Keep criteria atomic and separate automated checks from disclosed manual
checks. Preserve unsupported requested behavior rather than silently removing it;
do not add optional manual checks as mandatory feature criteria.'''


def planning_capabilities():
    package=TEMPLATE/'package.json'
    raw=package.read_bytes();declared=json.loads(raw)
    packages=set(declared.get('dependencies',{}))|set(declared.get('devDependencies',{}))
    return {'framework':'Next.js App Router','language':'TypeScript','node_major':24,
        'dependencies':declared.get('dependencies',{}),'dev_dependencies':declared.get('devDependencies',{}),
        'template_package_sha256':hashlib.sha256(raw).hexdigest(),
        'framework_entrypoints':{'home':'app/page.tsx','root_layout':'app/layout.tsx',
            'optional_http_handler':'app/api/<path-segments>/route.ts'},
        'storage':'Supported options: browser localStorage/sessionStorage for client-side storage, or server-only node:sqlite for SQLite. A server database is optional. No remote database adapter is installed.',
        'execution_checks':['typecheck','production_build'],
        'browser_coverage':'Independent requirements-derived semantic browser assertions run after source build. Supports accessible controls, visible text, values, counts and titles. Database restart, security and deployment are not browser coverage.',
        'test_frameworks_available':sorted(packages & {'jest','vitest','@testing-library/react'}),
        'network_and_packages':'No package installation or external services in generated-app execution.'}


def capability_fingerprint():
    return hashlib.sha256(json.dumps(planning_capabilities(),sort_keys=True,separators=(',',':')).encode()).hexdigest()


def manifest_issues(draft,root,*,executable=False):
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
        if executable and (is_test_source(file.path) or file.owner=='qa'):
            issues.append(f'{file.path}: QA produces an independent browser contract outside the source workspace; '
                'this execution pipeline has no test-file runner. Assign app source to a builder and describe checks in test_strategy.')
    if 'app/page.tsx' not in {f.path for f in draft.files}:
        issues.append('The Next.js runtime needs the home entry app/page.tsx; no business layout or API is prescribed.')
    return issues


def draft_task(store,job_id,description,*,action_limit=8,parent=None,inputs=None):
    ledger=TaskLedger(store,job_id)
    state=ledger.create(Task(owner='planner',goal='Propose a reviewable app design from the original request and clarification answers.',
        parent_id=parent.task.id if parent else None,
        dependencies=[Dependency(task_id=parent.task.id,revision=parent.revision)] if parent else [],
        inputs=inputs or {'original_request':description},required_checks=['draft_schema','workspace_manifest','implementation_review']),action_limit=action_limit)
    return ledger,state


def continue_draft(ledger,task_id,agents):
    directory=ledger.store.path.parent/'autonomous-plans'/ledger.job_id
    directory.mkdir(parents=True,exist_ok=True);candidate=directory/'candidate.json'
    def fingerprint():return hashlib.sha256(candidate.read_bytes() if candidate.exists() else b'').hexdigest()
    def context(state):
        current=fingerprint()
        events=ledger.store.read(ledger.job_id)['events']
        observations=[o for o in state.observations if o.revision==state.revision and o.fingerprint==current]
        # candidate.json is shared by successive design revisions. Only a proposal
        # observed for this task revision may be reused as current planning context.
        saved=next((e for e in reversed(events) if e['status']=='DESIGN_PROPOSED'
            and e['payload'].get('task_id')==state.task.id and e['payload'].get('revision')==state.revision
            and e['payload'].get('proposal_sha256')==current),None)
        bound=bool(saved) or any(any(c.check=='draft_schema' for c in o.checks) for o in observations)
        latest=json.loads(candidate.read_text(encoding='utf-8')) if bound and candidate.exists() else None
        invalid=None
        failed=next((e for e in reversed(events) if e['status']=='AGENT_VALIDATION_FAILED'
            and e['payload'].get('task_id')==state.task.id and e['payload'].get('task_revision')==state.revision
            and e['payload'].get('schema')=='AppDraft' and e['payload'].get('report')),None)
        if failed and (not saved or failed['sequence']>saved['sequence']):
            path=Path(failed['payload']['report']).resolve()
            if path.is_relative_to(ledger.store.path.parent.resolve()) and path.is_file() and path.stat().st_size<=160000:
                trace=json.loads(path.read_text(encoding='utf-8'))
                if (trace.get('job_id')==ledger.job_id and trace.get('task_id')==state.task.id
                    and trace.get('task_revision')==state.revision and not trace.get('output_truncated')):
                    try:invalid={'proposal':json.loads(trace['output']),'error':failed['payload']['summary']}
                    except (ValueError,KeyError):pass
        return {**state.task.inputs,'runtime_capabilities':planning_capabilities(),
            'verification_capabilities':browser_capabilities(),
            'latest_proposal':latest,'invalid_proposal':invalid,
            'implementation_findings':prior_review(ledger,state,AppDraft.model_validate(latest)) if latest else None,
            'recent_failures':[o.model_dump() for o in observations][-2:],
            'recovery_strategy':state.recovery.model_dump() if state.recovery else None}
    if getattr(agents,'trace_directory',None) is None:
        agents.trace_directory=ledger.store.path.parent/'model-calls'/ledger.job_id
    def planner(state):
        template_before=source_fingerprint(TEMPLATE)
        data=context(state)
        capabilities_before=hashlib.sha256(json.dumps(data['runtime_capabilities'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        record_handoff(ledger.store,ledger.job_id,'coordinator','planner',
            'Choose the application design and shared interfaces from the user goal; use observed feedback to revise it.',
            data,agents=agents,task_id=state.task.id,parent_task_id=state.task.parent_id,task_state=state)
        previous_activity=getattr(agents,'activity',None)
        try:
            agents.activity=lambda status,payload:ledger.store.event(ledger.job_id,status,payload,update_status=False)
            # Reviewer/service failure did not reject the planner's work. Resume
            # that candidate's technical checks instead of paying to rewrite it.
            rejected=any(o.fingerprint==fingerprint() for o in state.observations if o.revision==state.revision)
            proposed=AppDraft.model_validate(data['latest_proposal']) if data['latest_proposal'] and not rejected and not data['invalid_proposal'] else AppDraft.model_validate(agents.generate(AppDraft,INSTRUCTION,data,coding=True))
            candidate.write_text(proposed.model_dump_json(indent=2),encoding='utf-8',newline='\n')
            snapshot=directory/f'draft-{state.task.id}-r{state.revision}-a{state.actions_used}.json';snapshot.write_bytes(candidate.read_bytes())
            ledger.store.event(ledger.job_id,'DESIGN_PROPOSED',{'task_id':state.task.id,'revision':state.revision,
                'proposal_sha256':fingerprint(),'report':str(snapshot.resolve()),'scope':'Agent-authored candidate; internal review and execution have not passed.'},update_status=False)
        finally:agents.activity=previous_activity
        issues=manifest_issues(proposed,directory/'unexecuted-workspace',executable=True)+interface_issues(proposed)
        if source_fingerprint(TEMPLATE)!=template_before or capability_fingerprint()!=capabilities_before:
            issues.append('Runtime capabilities or scaffold changed during planning; inspect the current base and propose again.')
        technical=review_design(ledger,state,agents,proposed,data) if not issues else None
        findings=technical['decision']['issues'] if technical else []
        report=directory/f'check-{state.task.id}-r{state.revision}-a{state.actions_used}.json'
        report.write_text(json.dumps({'draft_sha256':fingerprint(),'draft_snapshot':str(snapshot.resolve()),'issues':issues,
            'implementation_review':technical,
            'template_fingerprint':template_before,'runtime_capabilities_sha256':capabilities_before,
            'scope':'Proposal structure and workspace manifest only; business completeness and execution remain unverified.'},indent=2),encoding='utf-8')
        return [CheckEvidence(check=name,exit_code=int(bool(issues)) if name=='workspace_manifest' else int(bool(issues) or bool(findings)) if name=='implementation_review' else 0,
            fingerprint=fingerprint(),report=str(report.resolve()),summary='; '.join(issues) if issues else
                '; '.join(issue['problem'] for issue in findings) if name=='implementation_review' and findings else
                'Draft protocol validated; app execution not performed.')
            for name in ['draft_schema','workspace_manifest','implementation_review']]
    reviewer=SeniorReviewer(agents,ledger,{'planner'},context_loader=context,
        capabilities={'planner':'Owns and can revise the complete app design, source manifest and shared interfaces while preserving the user goal.'})
    state=TaskCoordinator(ledger,{'planner':planner},reviewer,fingerprint).run(task_id)
    if state.status=='completed':
        draft=AppDraft.model_validate_json(candidate.read_text(encoding='utf-8'))
        snapshot=safe_path(directory,f'review-{task_id}-r{state.revision}-v{state.version}.json')
        raw=candidate.read_bytes()
        if snapshot.exists():
            if snapshot.read_bytes()!=raw:raise ValueError('The saved review snapshot changed; inspect it before continuing')
        else:
            with snapshot.open('xb') as file:file.write(raw)
        checks=json.loads(Path(state.observations[-1].checks[0].report).read_text(encoding='utf-8'))
        ledger.store.event(ledger.job_id,'AUTONOMOUS_DRAFT_READY',{'title':draft.title,'task_id':task_id,'revision':state.revision,
            'task_version':state.version,'review_snapshot_version':1,
            'report':str(snapshot.resolve()),'draft_sha256':fingerprint(),
            'template_fingerprint':checks['template_fingerprint'],'runtime_capabilities_sha256':checks['runtime_capabilities_sha256'],
            'approval':'NOT_APPROVED','app_execution':'NOT_RUN'})
    else:
        ledger.store.event(ledger.job_id,'AUTONOMOUS_PAUSED',{'task_id':task_id,'reason':state.pause_reason or state.status,
            'revision':state.revision,'app_execution':'NOT_RUN'})
    return ledger.store.read(ledger.job_id)


def plan_app(description,agents,store,*,action_limit=8):
    request=ApplicationRequest(description=description,model=agents.model_name)
    job=store.create({**request.model_dump(),'workflow':'autonomous'})
    return start_planning(job,agents,store,action_limit=action_limit)


def start_planning(job_id,agents,store,*,action_limit=8):
    """Start a controller-created job without creating a second identity/history."""
    record=store.read(job_id);received=record['events'][0]['payload']
    ledger=TaskLedger(store,job_id)
    if received.get('workflow')!='autonomous':raise ValueError('This job does not use autonomous planning')
    if record['status']!='RECEIVED' or ledger.list():
        raise ValueError('Planning was already dispatched; inspect and resume its saved tasks instead')
    request=ApplicationRequest(description=received['description'],model=received['model'])
    if agents.model_name!=request.model:raise ValueError('The planner must use the model selected for this job')
    intake=ledger.create(Task(owner='requirements',goal='Determine whether the user request is understood, needs business clarification or is outside scope.',
        inputs={'original_request':request.description},required_checks=['intake_schema']),action_limit=action_limit)
    return continue_intake(ledger,intake.task.id,agents)


def uses_autonomous_planning(record):
    marker=record['events'][0]['payload'].get('workflow')
    if marker is not None:return marker=='autonomous'
    return any(event['status'].startswith('AUTONOMOUS_') for event in record['events'])


def resumable_planning(record,store):
    if not uses_autonomous_planning(record) or record['status']!='AUTONOMOUS_PAUSED':return False
    try:
        pause=next(e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_PAUSED')
        state=TaskLedger(store,record['job_id']).read(pause['task_id'])
        return state.status=='paused' and state.task.owner in {'requirements','planner'} and state.inflight_role is None
    except (KeyError,StopIteration):return False


def resume_planning(job_id,agents,store,*,additional_actions=8,reconciled=False):
    record=store.read(job_id)
    if not uses_autonomous_planning(record) or record['status']!='AUTONOMOUS_PAUSED':
        raise ValueError('Only paused autonomous planning can resume here')
    if agents.model_name!=record['events'][0]['payload']['model']:raise ValueError('Use the saved job model when resuming')
    pause=next(e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_PAUSED')
    ledger=TaskLedger(store,job_id);state=ledger.read(pause['task_id'])
    if state.task.owner not in {'requirements','planner'}:raise ValueError('This task is not an intake/planning task')
    state=ledger.resume(state,additional_actions=additional_actions,reconciled=reconciled)
    resume=continue_intake if state.task.owner=='requirements' else continue_draft
    return resume(ledger,state.task.id,agents)


def continue_intake(ledger,task_id,agents):
    directory=ledger.store.path.parent/'autonomous-plans'/ledger.job_id;directory.mkdir(parents=True,exist_ok=True)
    route=directory/'intake.json'
    def fingerprint():return hashlib.sha256(route.read_bytes() if route.exists() else b'').hexdigest()
    def worker(state):
        data={'application_request':state.task.inputs['original_request'],
              'human_clarifications':state.task.inputs.get('human_clarifications',[]),
              'human_review_feedback':state.task.inputs.get('human_review_feedback',[]),
              'protocol_errors':[o.error for o in state.observations if o.revision==state.revision and o.error][-2:]}
        if state.recovery and state.reviewed_observations==len(state.observations):data['fresh_review']=state.recovery.model_dump()
        if getattr(agents,'trace_directory',None) is None:agents.trace_directory=ledger.store.path.parent/'model-calls'/ledger.job_id
        record_handoff(ledger.store,ledger.job_id,'coordinator','requirements',
            'Establish the business scope before architecture; optional implementation choices are delegated to the planner.',
            data,agents=agents,task_id=state.task.id,parent_task_id=state.task.parent_id,task_state=state)
        previous_activity=getattr(agents,'activity',None)
        try:
            agents.activity=lambda status,payload:ledger.store.event(ledger.job_id,status,payload,update_status=False)
            decision=agents.generate(IntakeDecision,INTAKE_INSTRUCTION,data)
        finally:agents.activity=previous_activity
        if decision.root.intent=='clarify':
            normalized=lambda text:' '.join(text.casefold().split()).rstrip('?.!')
            answered={normalized(item['question']):item for item in data['human_clarifications']
                if isinstance(item,dict) and item.get('question') and item.get('answer','').strip()}
            duplicates=[answered[normalized(question)] for question in decision.root.questions if normalized(question) in answered]
            if duplicates:raise ValueError('Intake repeated an already answered question. Use these user decisions instead of asking again: '+json.dumps(duplicates))
            routing=review_clarification(ledger,state,agents,data,decision)
            if routing.disposition=='delegate_to_planner':decision=IntakeDecision.model_validate({'intent':'build'})
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
