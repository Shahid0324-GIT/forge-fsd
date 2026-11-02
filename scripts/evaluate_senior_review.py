"""Replay saved planning failures to the real reviewer; does not build or repair an app."""
import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from forge.agents import OllamaAgents
from forge.coordinator import TaskCoordinator
from forge.operations_design import ApiProposal,compile_operations
from forge.persistence import JobStore
from forge.schemas import AppBrief
from forge.senior_review import SeniorReviewer
from forge.tasks import CheckEvidence,Observation,Task,TaskLedger,TaskConflict


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-directory',type=Path,required=True)
    args=parser.parse_args();case=args.case_directory
    saved=json.loads((case/'job.json').read_text(encoding='utf-8'))
    brief=AppBrief.model_validate(next(e['payload'] for e in saved['events'] if e['status']=='REQUIREMENTS_READY'))
    request=saved['events'][0]['payload'].get('description','')
    proposals=[]
    for path in (case/'model-calls').glob('*.json'):
        call=json.loads(path.read_text(encoding='utf-8'))
        if call['schema']=='ApiProposal' and call.get('done_reason')=='stop':proposals.append((call['started_at'],path,call))
    failures=[]
    for _,path,call in sorted(proposals):
        try:compile_operations(brief,ApiProposal.model_validate_json(call['output']))
        except ValueError as exc:failures.append((path,call,str(exc)))
    if not failures:raise SystemExit('No saved API planning failure reproduced; this diagnostic replay needs actual failure evidence.')
    directory=Path('artifacts/recovery-evaluation')/uuid4().hex
    store=JobStore(directory/'jobs.sqlite3');job=store.create({'description':'Historical planning diagnostic replay; no app execution'})
    ledger=TaskLedger(store,job)
    task=ledger.create(Task(owner='planner',goal='Diagnose the recorded planning blocker and route a concrete correction to its responsible owner.',
        inputs={'original_request':request,'business_brief':brief.model_dump(),
                'rejected_proposal':json.loads(failures[-1][1]['output'])},required_checks=['planning_contract']),action_limit=4)
    task=ledger.start(task)
    for path,_,error in failures[-2:]:
        fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
        task=ledger.observe(task,Observation(revision=1,fingerprint=fingerprint,
            checks=[CheckEvidence(check='planning_contract',exit_code=1,fingerprint=fingerprint,report=str(path.resolve()),summary=error)]))
    agents=OllamaAgents('qwen2.5-coder:7b');agents.trace_directory=directory/'model-calls'
    def no_execution(state):
        ledger.pause(state,'Diagnostic replay ends before executing the proposed app repair.',action_finished=True)
        raise TaskConflict('Diagnostic replay does not execute app repairs')
    workers={'builder':no_execution,'planner':no_execution}
    reviewer=SeniorReviewer(agents,ledger,set(workers),capabilities={
        'builder':'Implements application source against the current shared design; escalates changes to shared contracts to their planner owner.',
        'planner':'Owns the current planning proposal, shared interface declarations and architecture; can revise the rejected proposal without discarding user functionality.'})
    result=TaskCoordinator(ledger,workers,reviewer,lambda:fingerprint,review_after=min(2,len(failures))).run(task.task.id)
    summary={'job_id':job,'task_id':task.task.id,'status':result.status,
        'historical_failures_reproduced':min(2,len(failures)),
        'new_model_calls':len(list((directory/'model-calls').glob('*.json'))),
        'recovery':result.recovery.model_dump() if result.recovery else None,'review_error':result.review_error,
        'app_execution':'NOT_RUN','scope':'Historical diagnostics reviewed; proposed repair effectiveness is unproven.'}
    (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    (directory/'job.json').write_text(json.dumps(store.read(job),indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(directory),**summary}),flush=True)
    return int(result.recovery is None)


if __name__=='__main__':raise SystemExit(main())
