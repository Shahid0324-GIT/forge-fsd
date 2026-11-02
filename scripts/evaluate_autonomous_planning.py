"""Live agent-authored design proposals; no approval, app execution or deployment."""
import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from forge.agents import OllamaAgents
from forge.autonomous_planning import plan_app
from forge.persistence import JobStore


CASES={
    'landing':'Create a responsive landing page for a small bakery. Show its story, opening hours, menu highlights and a contact call to action. No saved data, accounts or external services are needed.',
    'calculator':'Build a tip calculator. Enter a bill, tip percentage and party size. Show the tip, total and amount per person. Reject negative bills and zero party size. No saved data is needed.',
    'expense':'Build a small expense tracker. Add, edit and delete expenses with title, amount, category and date. Show total spending, reject empty titles and nonpositive amounts, and keep expenses after restarting. Use local data; no accounts or external services.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',nargs='+',choices=CASES,default=list(CASES))
    args=parser.parse_args();root=Path('artifacts/autonomous-planning-evaluation')/uuid4().hex
    root.mkdir(parents=True);results=[]
    (root/'source-snapshot.json').write_text(json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('src/forge').glob('*.py'))},indent=2),encoding='utf-8')
    print('Evidence: '+str(root),flush=True)
    for case in args.cases:
        directory=root/case;directory.mkdir();agent=OllamaAgents('qwen2.5-coder:7b');agent.trace_directory=directory/'model-calls'
        store=JobStore(directory/'jobs.sqlite3');start=perf_counter()
        record=plan_app(CASES[case],agent,store)
        (directory/'job.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
        result={'case':case,'status':record['status'],'seconds':round(perf_counter()-start,2),
            'model_calls':len(list((directory/'model-calls').glob('*.json'))),
            'recovery_reviews':sum(e['status']=='TASK_RECOVERY_PLANNED' for e in record['events']),
            'semantic_review':'PENDING','app_execution':'NOT_RUN','evidence':str(directory)}
        results.append(result);(root/'summary.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
    return int(any(r['status']!='AUTONOMOUS_DRAFT_READY' for r in results))


if __name__=='__main__':raise SystemExit(main())
