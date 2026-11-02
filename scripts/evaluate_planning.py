"""Live, isolated planning evaluation. Does not approve, build, publish or deploy apps."""
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from forge.agents import OllamaAgents
from forge.handoffs import record_handoff
from forge.persistence import JobStore
from forge.workflow import run_job


ROOT=Path(__file__).resolve().parents[1]
CASES={
    'calculator':'Build a tip calculator. Enter a bill, tip percentage and party size. Show the tip, total and amount per person. Reject negative bills and zero party size. No saved data is needed.',
    'expense':'Build an expense tracker with add, edit and delete, categories, spending totals, and saved data that survives restarting.',
    'inventory':'Build a small stockroom app. Keep products with a name and unique SKU and stock movements linked to products. Record stock in and out, calculate current stock, reject stock out beyond available stock, and retain records after restarting.',
}


def no_active_worker():
    path=ROOT/'artifacts/jobs.sqlite3'
    if not path.exists():return
    with sqlite3.connect(path) as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='operations'").fetchone()
        if exists and db.execute("SELECT 1 FROM operations WHERE status='RUNNING'").fetchone():
            raise SystemExit('A dashboard operation is active. Wait before competing for local inference.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',nargs='+',choices=CASES,default=list(CASES))
    parser.add_argument('--repeats',type=int,choices=[1,2,3],default=2)
    parser.add_argument('--model',choices=['qwen2.5-coder:3b','qwen2.5-coder:7b'],default='qwen2.5-coder:7b')
    args=parser.parse_args();directory=ROOT/'artifacts/planning-evaluation'/uuid4().hex
    directory.mkdir(parents=True);results=[]
    (directory/'source-snapshot.json').write_text(json.dumps({str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src/forge').glob('*.py'))},indent=2),encoding='utf-8')
    print('Evidence: '+str(directory),flush=True)
    for case in args.cases:
        for repeat in range(args.repeats):
            no_active_worker()
            path=directory/f'{case}-{repeat+1}';path.mkdir()
            store=JobStore(path/'jobs.sqlite3');agents=OllamaAgents(args.model)
            agents.trace_directory=path/'model-calls'
            agents.activity=lambda status,payload:store.event(agents.invocation_context['job_id'],status,payload,update_status=False)
            agents.handoff=lambda sender,recipient,summary,context:record_handoff(store,agents.invocation_context['job_id'],sender,recipient,summary,context,agents=agents)
            start=perf_counter();record=run_job(CASES[case],agents,store)
            (path/'job.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
            review=next((e['payload'] for e in reversed(record['events']) if e['status']=='PLAN_REVIEW'),None)
            failure=next((e['payload'] for e in reversed(record['events']) if e['status']=='FAILED'),None)
            result={'case':case,'repeat':repeat+1,'model':args.model,'status':record['status'],
                    'wall_seconds':round(perf_counter()-start,2),'structurally_reviewable':review is not None,
                    'semantic_review':'PENDING','app_execution':'NOT_RUN','failure':failure,
                    'model_calls':len(list((path/'model-calls').glob('*.json'))),'evidence':str(path)}
            results.append(result)
            (directory/'summary.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
            print(json.dumps(result),flush=True)
    return int(any(not result['structurally_reviewable'] for result in results))


if __name__=='__main__':raise SystemExit(main())
