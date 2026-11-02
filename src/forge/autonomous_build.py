"""Approved source generation and build verification. No behavior/readiness promotion."""
from pathlib import Path

from forge import autonomous_planning as planning
from forge.autonomous_review import approved_review
from forge.coordinator import TaskCoordinator
from forge.senior_review import SeniorReviewer
from forge.source_agent import SourceAgent,build_evidence
from forge.source_checks import run_source_checks
from forge.tasks import Dependency,Observation,Task,TaskLedger
from forge.workspace import safe_path,seed_workspace,source_fingerprint
from forge.workspace_tools import WorkspaceTools,file_hash


PROJECT=Path(__file__).resolve().parents[2]


def build_resumable(record,store):
    if record['status']!='AUTONOMOUS_BUILD_PAUSED':return False
    try:
        event=next(e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_BUILD_PAUSED')
        state=TaskLedger(store,record['job_id']).read(event['task_id'])
        approved_review(record['job_id'],store)
        return state.inflight_role is None and state.status in {'paused','completed','needs_refresh'}
    except (ValueError,OSError,KeyError,StopIteration):return False


def build_app(job_id,agents,store,*,resume=False,additional_actions=8,workspace_boundary=None,check_runner=run_source_checks):
    record=store.read(job_id)
    expected='AUTONOMOUS_BUILD_PAUSED' if resume else 'AUTONOMOUS_APPROVED'
    if record['status']!=expected:raise ValueError('Build requires an approved plan or explicit resume of a saved build pause')
    review=approved_review(job_id,store)
    if agents.model_name!=review['binding']['model']:raise ValueError('Use the approved job model for generation')
    boundary=Path(workspace_boundary) if workspace_boundary else PROJECT/'workspace'
    root=safe_path(boundary,job_id)
    draft=planning.AppDraft.model_validate(review['draft']);ledger=TaskLedger(store,job_id)
    def authorize():
        if approved_review(job_id,store)['fingerprint']!=review['fingerprint']:raise ValueError('Reviewed plan changed during execution')
    if resume:
        if not build_resumable(record,store):raise ValueError('Inspect interrupted work and authorization before resuming')
        pending=next(e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_BUILD_PAUSED')
        state=ledger.read(pending['task_id'])
        if state.status=='paused':ledger.resume(state,additional_actions=additional_actions)
    parents=[state for state in ledger.list() if state.task.inputs.get('stage')=='approved_build']
    if len(parents)>1:raise ValueError('Multiple execution records need reconciliation')
    if not parents:
        if root.exists():raise ValueError('An untracked workspace exists; refusing to overwrite it')
        seed_workspace(planning.TEMPLATE,root,generic=True)
        parent=ledger.start(ledger.create(Task(owner='coordinator',goal='Generate the approved app and verify its final build.',
            inputs={'stage':'approved_build','review_fingerprint':review['fingerprint']},
            dependencies=[Dependency(task_id=review['binding']['task_id'],revision=review['binding']['revision'])],
            required_checks=['isolated_build'])))
    else:
        parent=parents[0]
        if parent.task.inputs['review_fingerprint']!=review['fingerprint'] or not root.is_dir():
            raise ValueError('Saved execution does not match this approval/workspace')
    store.event(job_id,'AUTONOMOUS_BUILDING',{'task_id':parent.task.id,'review_fingerprint':review['fingerprint'],
        'scope':'Source generation and isolated typecheck/build only. App behavior, preview and publication remain unverified.'})
    capabilities={role:'Owns only: '+', '.join(file.path for file in draft.files if file.owner==role)
        for role in {file.owner for file in draft.files}}
    def reviewer_for(roles):return SeniorReviewer(agents,ledger,set(roles),context_loader=lambda state:{
        'original_request':review['binding']['inputs']['original_request'],'approved_design':draft.model_dump(),
        'current_source':{file.path:safe_path(root,file.path).read_text(encoding='utf-8')
            for file in draft.files if safe_path(root,file.path).is_file()}},capabilities={role:capabilities[role] for role in roles})
    writer=SourceAgent(ledger,agents,root,draft,workspace_boundary=boundary,check_runner=check_runner,authorization=authorize)
    context={key:review['binding']['inputs'].get(key,[] if key!='original_request' else '')
        for key in ['original_request','human_clarifications','human_review_feedback']}
    def children():return [state for state in ledger.list() if state.task.parent_id==parent.task.id]
    def child(stage,owner,goal,inputs,dependencies,checks):
        matches=[state for state in children() if state.task.inputs.get('stage')==stage and state.task.inputs.get('file')==inputs.get('file')]
        if len(matches)>1:raise ValueError('Duplicate build tasks need reconciliation')
        if not matches:
            return ledger.create(Task(parent_id=parent.task.id,owner=owner,goal=goal,
                inputs={**context,**inputs,'stage':stage,'review_fingerprint':review['fingerprint']},
                dependencies=dependencies,required_checks=checks),action_limit=8)
        state=matches[0]
        if state.status=='needs_refresh':
            if state.inflight_role is not None:raise ValueError('Inspect an interrupted task before refreshing its inputs')
            state=ledger.revise(state,state.task.model_copy(update={'dependencies':dependencies}))
        return state
    def pause(state,reason=None):
        authorize()
        store.event(job_id,'AUTONOMOUS_BUILD_PAUSED',{'task_id':state.task.id,'parent_task_id':parent.task.id,
            'reason':reason or state.pause_reason or state.status,'source_fingerprint':source_fingerprint(root),
            'app_behavior':'NOT_TESTED','app_execution':'BUILD_NOT_VERIFIED'})
        return store.read(job_id)
    source_tasks=[state for state in children() if state.task.inputs.get('stage')=='generate']
    existing_check=next((state for state in children() if state.task.inputs.get('stage')=='verify'),None)
    if existing_check is None or any(state.status!='completed' for state in source_tasks):
        previous=None
        for file in draft.files:
            authorize()
            dependencies=[Dependency(task_id=review['binding']['task_id'],revision=review['binding']['revision'])]
            if previous:dependencies.append(Dependency(task_id=previous.task.id,revision=previous.revision))
            state=child('generate',file.owner,f'Implement {file.path}: {file.purpose}',{'file':file.path},dependencies,['source_written'])
            state=TaskCoordinator(ledger,{file.owner:writer},reviewer_for({file.owner}),
                lambda path=file.path:file_hash(safe_path(root,path)) or '0'*64).run(state.task.id)
            if state.status!='completed':return pause(state)
            previous=state
        source_tasks=[state for state in children() if state.task.inputs.get('stage')=='generate']
    last=source_tasks[-1]
    state=child('verify',draft.files[0].owner,'Make the final approved source pass actual isolated build checks without weakening requirements.',
        {'mode':'repair_build'},[Dependency(task_id=last.task.id,revision=last.revision)],['isolated_build'])
    fresh_check=resume
    def verify_or_repair(current):
        nonlocal fresh_check
        authorize()
        failure=next((o for o in reversed(current.observations) if o.revision==current.revision
            and any(c.check=='isolated_build' and c.exit_code!=0 for c in o.checks)),None)
        if failure is None or fresh_check:
            fresh_check=False
            return build_evidence(WorkspaceTools(ledger,current,root,draft,workspace_boundary=boundary,
                check_runner=check_runner,authorization=authorize))
        return writer(current)
    state=TaskCoordinator(ledger,{role:verify_or_repair for role in capabilities},reviewer_for(capabilities),lambda:source_fingerprint(root)).run(state.task.id)
    if state.status!='completed':return pause(state)
    authorize();checks=state.observations[-1].checks;fingerprint=source_fingerprint(root)
    if any(check.fingerprint!=fingerprint for check in checks):return pause(state,'Source changed after verification; run fresh checks')
    parent=ledger.read(parent.task.id)
    ledger.observe(parent,Observation(revision=parent.revision,fingerprint=fingerprint,checks=checks))
    store.event(job_id,'AUTONOMOUS_BUILD_CHECKS_PASSED',{'task_id':state.task.id,'source_fingerprint':fingerprint,
        'review_fingerprint':review['fingerprint'],'report':checks[0].report,
        'application_behavior':'NOT_TESTED','preview':'NOT_APPROVED','publishing':'NOT_APPROVED',
        'scope':'TypeScript and production build passed for this source; this is not app readiness.'})
    return store.read(job_id)
