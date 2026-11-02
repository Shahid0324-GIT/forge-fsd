"""Review/decision binding for autonomous designs; approval never proves app correctness."""
import hashlib
import json
from pathlib import Path

from forge import autonomous_planning as planning
from forge.persistence import now
from forge.tasks import TaskLedger
from forge.workspace import safe_path,source_fingerprint


def review_snapshot(job_id,store):
    record=store.read(job_id)
    if not planning.uses_autonomous_planning(record):raise ValueError('This is not an autonomous job')
    ready=next((e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_DRAFT_READY'),None)
    if not ready or ready.get('review_snapshot_version')!=1:raise ValueError('Create a fresh reviewable proposal first')
    ledger=TaskLedger(store,job_id);state=ledger.read(ready['task_id'])
    if state.status!='completed' or state.revision!=ready['revision'] or state.version!=ready['task_version']:
        raise ValueError('The planning task changed; review its current revision')
    directory=store.path.parent/'autonomous-plans'/job_id
    path=safe_path(directory,f'review-{state.task.id}-r{state.revision}-v{state.version}.json')
    if Path(ready['report']).resolve()!=path.resolve():raise ValueError('Proposal report does not match its saved task')
    if path.stat().st_size>100000:raise ValueError('Proposal exceeds the review budget')
    raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    if digest!=ready['draft_sha256'] or hashlib.sha256(safe_path(directory,'candidate.json').read_bytes()).hexdigest()!=digest:
        raise ValueError('The proposal changed; review a fresh snapshot')
    draft=planning.AppDraft.model_validate_json(raw)
    if planning.manifest_issues(draft,directory/'unexecuted-workspace'):raise ValueError('The source manifest is no longer valid')
    observation=state.observations[-1]
    if observation.revision!=state.revision or observation.fingerprint!=digest or ledger.failures(state,observation):
        raise ValueError('The proposal lacks current passing structural checks')
    for dependency in state.task.dependencies:
        upstream=ledger.read(dependency.task_id)
        if upstream.status!='completed' or upstream.revision!=dependency.revision:raise ValueError('Requirements changed after planning')
    if ready['template_fingerprint']!=source_fingerprint(planning.TEMPLATE) or ready['runtime_capabilities_sha256']!=planning.capability_fingerprint():
        raise ValueError('The runtime changed; create a new proposal before building')
    binding={'job_id':job_id,'task_id':state.task.id,'revision':state.revision,'task_version':state.version,
        'draft_sha256':digest,'inputs':state.task.inputs,'model':record['events'][0]['payload']['model'],
        'template_fingerprint':ready['template_fingerprint'],'runtime_capabilities_sha256':ready['runtime_capabilities_sha256'],
        'scope':'Generate source and run isolated development checks. A build pass does not establish app behavior. Preview, publishing and deployment require separate approval.'}
    fingerprint=hashlib.sha256(json.dumps(binding,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'fingerprint':fingerprint,'binding':binding,'draft':draft.model_dump(),'report':str(path.resolve())}


def decide_plan(job_id,store,fingerprint,*,approved,actor):
    if type(approved) is not bool:raise ValueError('Supply an explicit approval or rejection decision')
    if not actor:raise ValueError('Record the decision actor')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if store.read(job_id)['status']!='AUTONOMOUS_DRAFT_READY':raise ValueError('Only the current proposal can be decided')
        review=review_snapshot(job_id,store)
        if fingerprint!=review['fingerprint']:raise ValueError('The reviewed proposal changed; inspect it before deciding')
        status='AUTONOMOUS_APPROVED' if approved else 'AUTONOMOUS_REJECTED'
        payload={**review,'actor':actor,'approval':'APPROVED' if approved else 'REJECTED','app_execution':'NOT_RUN'}
        db.execute('UPDATE jobs SET status=? WHERE id=?',(status,job_id))
        db.execute('INSERT INTO events(job_id,timestamp,status,payload) VALUES (?,?,?,?)',
            (job_id,now(),status,json.dumps(payload)))
    return store.read(job_id)


def approved_review(job_id,store):
    record=store.read(job_id)
    if record['status'] not in {'AUTONOMOUS_APPROVED','AUTONOMOUS_BUILDING','AUTONOMOUS_BUILD_PAUSED','AUTONOMOUS_BUILD_CHECKS_PASSED'}:
        raise ValueError('This job is not authorized for source generation')
    approved=next((e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_APPROVED'),None)
    if not approved:raise ValueError('Source generation requires approval of the current plan')
    review=review_snapshot(job_id,store)
    if approved['fingerprint']!=review['fingerprint']:raise ValueError('The plan or runtime changed after approval')
    return review


def request_changes(job_id,agents,store,fingerprint,feedback,*,actor):
    if not isinstance(feedback,str) or not feedback.strip() or len(feedback)>2000:
        raise ValueError('Describe the requested changes in 1–2000 characters')
    if not actor:raise ValueError('Record the review actor')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if store.read(job_id)['status']!='AUTONOMOUS_DRAFT_READY':raise ValueError('Only an unapproved proposal can be revised here')
        review=review_snapshot(job_id,store)
        if fingerprint!=review['fingerprint']:raise ValueError('Review the current proposal before requesting changes')
        if agents.model_name!=review['binding']['model']:raise ValueError('Use the saved job model for review changes')
        ledger=TaskLedger(store,job_id);planner=ledger.read(review['binding']['task_id'])
        if not planner.task.parent_id:raise ValueError('The saved requirements task is missing')
        intake=ledger.read(planner.task.parent_id)
        if intake.task.owner!='requirements' or intake.status!='completed':raise ValueError('Inspect the requirements task before revising this proposal')
        db.execute('UPDATE jobs SET status=? WHERE id=?',('AUTONOMOUS_REPLANNING',job_id))
        db.execute('INSERT INTO events(job_id,timestamp,status,payload) VALUES (?,?,?,?)',
            (job_id,now(),'AUTONOMOUS_REPLANNING',json.dumps({'actor':actor,'feedback':feedback.strip(),
                'review_fingerprint':fingerprint,'task_id':review['binding']['task_id'],'app_execution':'NOT_RUN'})))
    inputs={**intake.task.inputs,'human_review_feedback':[*intake.task.inputs.get('human_review_feedback',[]),feedback.strip()]}
    intake=ledger.revise(intake,intake.task.model_copy(update={'inputs':inputs}))
    return planning.continue_intake(ledger,intake.task.id,agents)
