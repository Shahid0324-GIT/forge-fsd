"""Business-only autonomous app evaluation, with preserved source and resumable evidence.

Approval is by an internal evaluation actor, never a claim of human approval.
No source fixes, preview, deployment, silent model switch or assertion relaxation.
"""
import argparse
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from forge.agents import OllamaAgents
from forge.autonomous_build import build_app
from forge.autonomous_planning import plan_app,resume_planning
from forge.autonomous_review import decide_plan,review_snapshot
from forge.autonomous_testing import test_app,evidence_current
from forge.persistence import JobStore
from forge.source_checks import PROJECT
from forge.tasks import TaskLedger
from forge.workspace import source_fingerprint


CASES={
    'counter':'Build a single-page counter. Start at zero. Increment adds one, Decrement subtracts one including below zero, and Reset returns to zero. No saved data or external services.',
    'notes':'Build a small personal notes app. I can add a note with a title and body, edit it, delete it, and see saved notes after reloading. Reject empty titles visibly. No login or external services.',
    'expenses':'Build a personal expense tracker. Add, edit and delete expenses with description, amount, category and date. Show total spending and filter by category. Reject empty descriptions and zero or negative amounts visibly. Keep expenses after reloading using SQLite. No login or external services.',
}
MODELS=['qwen2.5-coder:7b','groq:openai/gpt-oss-20b','groq:openai/gpt-oss-120b']
EVIDENCE=PROJECT/'artifacts/autonomous-flow-evaluation'
BOUNDARY=PROJECT/'workspace/.flow-evaluations'


def run_flow(record,agents,store,boundary,*,resume=False):
    """Stop at a broken boundary; a resume uses the saved task and frozen assertions."""
    job=record['job_id'];status=record['status']
    if resume and status=='AUTONOMOUS_PAUSED':record=resume_planning(job,agents,store,additional_actions=4)
    elif resume and status=='AUTONOMOUS_BUILD_PAUSED':record=build_app(job,agents,store,resume=True,additional_actions=4,workspace_boundary=boundary)
    elif resume and status=='AUTONOMOUS_TEST_PAUSED':record=test_app(job,agents,store,resume=True,additional_actions=4,workspace_boundary=boundary)
    if record['status']=='AUTONOMOUS_DRAFT_READY':
        review=review_snapshot(job,store)
        (store.path.parent/'review.json').write_text(json.dumps(review,indent=2),encoding='utf-8')
        record=decide_plan(job,store,review['fingerprint'],approved=True,actor='internal_evaluation')
    if record['status']=='AUTONOMOUS_APPROVED':record=build_app(job,agents,store,workspace_boundary=boundary)
    if record['status']=='AUTONOMOUS_BUILD_CHECKS_PASSED':record=test_app(job,agents,store,workspace_boundary=boundary)
    return record


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=CASES,default='notes')
    parser.add_argument('--model',choices=MODELS,default='qwen2.5-coder:7b')
    parser.add_argument('--resume',type=Path,help='Resume a saved evaluation directory without regenerating its completed stages.')
    args=parser.parse_args();EVIDENCE.mkdir(parents=True,exist_ok=True)
    if args.resume:
        directory=args.resume.resolve()
        if directory.parent!=EVIDENCE.resolve() or not directory.is_dir():raise ValueError('Resume must name a saved evaluation directly under '+str(EVIDENCE))
        config=json.loads((directory/'config.json').read_text(encoding='utf-8'))
        if config['case'] not in CASES or config['model'] not in MODELS or config['description']!=CASES[config['case']]:raise ValueError('Saved evaluation configuration changed')
    else:
        directory=EVIDENCE/uuid4().hex;directory.mkdir()
        config={'case':args.case,'model':args.model,'description':CASES[args.case]}
        (directory/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    print('Evidence: '+str(directory),flush=True)
    store=JobStore(directory/'jobs.sqlite3');agents=OllamaAgents(config['model'])
    agents.trace_directory=directory/'model-calls';start=perf_counter();record=None
    summary={**config,'passed':False,'human_approval':'NOT_CLAIMED','approval_actor':'internal_evaluation',
        'preview':'NOT_STARTED','deployment':'NOT_RUN','source_preserved':True}
    try:
        if args.resume:
            jobs=store.list_jobs()
            if len(jobs)!=1:raise ValueError('Resume requires exactly one saved evaluation job')
            record=store.read(jobs[0]['job_id']);received=record['events'][0]['payload']
            if received['description']!=config['description'] or received['model']!=config['model']:raise ValueError('Saved job and evaluation configuration disagree')
        else:record=plan_app(config['description'],agents,store,action_limit=4)
        record=run_flow(record,agents,store,BOUNDARY,resume=bool(args.resume))
        summary['passed']=record['status']=='AUTONOMOUS_APP_CHECKS_PASSED' and evidence_current(record,store,workspace_boundary=BOUNDARY)
    except Exception as exc:
        # Runtime/provider adapters already sanitize external error bodies.
        summary['error']=f'{type(exc).__name__}: {exc}'[:1800]
    finally:
        jobs=store.list_jobs()
        if len(jobs)==1:
            record=store.read(jobs[0]['job_id']);job=record['job_id'];root=BOUNDARY/job
            summary.update(job_id=job,status=record['status'],workspace=str(root),
                source_fingerprint=source_fingerprint(root) if root.is_dir() else None,
                tasks=[{'owner':task.task.owner,'status':task.status,'actions':task.actions_used,
                    'pause_reason':task.pause_reason,'pause_kind':task.pause_kind,
                    'errors':[observation.error for observation in task.observations if observation.error]}
                    for task in TaskLedger(store,job).list()])
            (directory/'job.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        summary.update(model_calls=len(list((directory/'model-calls').glob('*.json'))),seconds=round(perf_counter()-start,2),
            scope='Current build plus complete frozen browser coverage only; no deployment or general reliability claim.')
        (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)
    return int(not summary['passed'])


if __name__=='__main__':raise SystemExit(main())
