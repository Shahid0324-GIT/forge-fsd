"""Repair controlled counter/formatter fixtures using actual builds and frozen browser assertions.

Initial source is deliberately broken test data, not an agent-generated app claim.
After repair begins, only model tool calls may edit source. No preview or deployment.
"""
import argparse
import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

from forge.agents import OllamaAgents
from forge.autonomous_planning import AppDraft
from forge.coordinator import TaskCoordinator
from forge.persistence import JobStore
from forge.repair_fixture_browser import CASES,run_fixture_browser
from forge.senior_review import SeniorReviewer
from forge.source_agent import SourceAgent,build_evidence
from forge.source_checks import PROJECT,run_source_checks
from forge.tasks import Observation,Task,TaskLedger
from forge.workspace import safe_path,seed_workspace,source_fingerprint
from forge.workspace_tools import WorkspaceTools


FIXTURES={
    'client-boundary':{
        'request':'Build a counter displaying Count: 0 initially. Increment adds one per click; Reset returns to zero. No saved data. Keep page title metadata.',
        'files':{
            'app/page.tsx':"use client;\nimport {useState} from 'react';\nexport default function Page(){const [count,setCount]=useState(0);return <main><output>Count: {count}</output><button onClick={()=>setCount(count+1)}>Increment</button><button onClick={()=>setCount(0)}>Reset</button></main>}\nexport const metadata={title:'Counter App'};\n",
            'app/layout.tsx':"import type {ReactNode} from 'react';\nexport default function Layout({children}:{children:ReactNode}){return <html lang='en'><body>{children}</body></html>}\n",
        },
        'criteria':['Initially show Count: 0','Each Increment click adds one','Reset returns the counter to zero','Keep page title metadata'],
        'initial_failure':'typecheck',
    },
    'counter':{
        'request':'Build a counter. Display Count: 0 initially. The Increment button adds exactly one on each click. No saved data.',
        'files':{
            'app/page.tsx':"import Counter from './components/Counter';\nexport default function Page(){return <main><h1>Counter</h1><Counter start={0}/></main>}\n",
            'app/components/Counter.tsx':"import {useState} from 'react';\nexport function Counter({initial}:{initial:number}){const [count,setCount]=useState(initial);return <section><output>Count: {count}</output><button onClick={()=>setCount(count+2)}>Increment</button></section>}\n",
        },
        'criteria':['Initially show Count: 0','Each Increment click adds one, including repeated clicks'],
        'initial_failure':'typecheck',
    },
    'formatter':{
        'request':'Build a text formatter with a Name input and Format button. Display the submitted name trimmed of surrounding whitespace and converted to uppercase. No saved data.',
        'files':{
            'app/page.tsx':"'use client';\nimport {useState} from 'react';\nimport {formatName} from '../lib/format';\nexport default function Page(){const [name,setName]=useState('');const [result,setResult]=useState('');return <main><h1>Name formatter</h1><label>Name<input value={name} onChange={e=>setName(e.target.value)}/></label><button onClick={()=>setResult(formatName(name))}>Format</button><output>{result}</output></main>}\n",
            'lib/format.ts':"export function formatName(value:string):string{return value.trim().toLowerCase()}\n",
        },
        'criteria':['Format Ada as ADA','Format names with surrounding whitespace, such as two spaces around Sam, as SAM'],
        'initial_failure':'browser_acceptance',
    },
}


def verification_runner(directory,job,fixture):
    def verify(root,*_):
        report=run_source_checks(root,directory/'build-checks',job)
        if not report['passed']:return report
        build_path=report['report']
        browser=run_fixture_browser(root,directory/'browser-checks'/uuid4().hex,job,fixture,report['image'])
        failures=[row for row in browser.get('browser',{}).get('results',[]) if row.get('passed') is not True]
        output=json.dumps({'failures':failures,'error':browser.get('error'),
            'scope':browser['scope'],'cleanup_errors':browser['cleanup_errors']},separators=(',',':'))
        report['checks']['results'].append({'name':'browser_acceptance','exit_code':0 if browser['passed'] else 1,
            'stopped':None,'output':output})
        report['build_report']=build_path;report['fixture_browser_report']=browser['report']
        report['fixture_browser_harness_fingerprint']=browser['harness_fingerprint']
        report['cleanup_errors'].extend(browser['cleanup_errors'])
        report['coverage']['fixture_browser']='PASSED' if browser['passed'] else 'FAILED'
        report['coverage']['application_behavior']='PARTIAL_FROZEN_FIXTURE_ONLY'
        report['passed']=bool(browser['passed'] and browser['source_fingerprint']==report['source_fingerprint']
            and browser['app_image']==report['image'] and source_fingerprint(root)==report['source_fingerprint'])
        report['checks']['passed']=report['passed']
        target=directory/'combined';target.mkdir(exist_ok=True)
        path=target/(uuid4().hex+'.json');report['report']=str(path.resolve())
        path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        return report
    return verify


def evaluate(directory,name,action_limit):
    fixture=FIXTURES[name];directory.mkdir(parents=True)
    store=JobStore(directory/'jobs.sqlite3');job=store.create({'description':'Internal frozen repair fixture: '+name})
    ledger=TaskLedger(store,job);boundary=PROJECT/'workspace/.repair-fixtures';root=boundary/job
    draft=AppDraft(title=name,design='Controlled regression fixture; inspect the existing modules and choose corrections independently.',
        database='none',files=[{'path':path,'owner':'builder','purpose':'Regression fixture source'} for path in fixture['files']],
        acceptance_criteria=fixture['criteria'],test_strategy='Independent frozen browser assertions in a separate container, plus TypeScript and production build.')
    summary={'fixture':name,'job_id':job,'passed':False,'cleanup_errors':[],
        'scope':'Repair evaluation of controller-authored broken fixtures; not app generation or general readiness.'}
    agent=OllamaAgents('qwen2.5-coder:7b');agent.trace_directory=directory/'model-calls'
    try:
        seed_workspace(PROJECT/'templates/task-app',root,generic=True)
        for path,content in fixture['files'].items():
            target=safe_path(root,path);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(content,encoding='utf-8')
        check=verification_runner(directory,job,name)
        state=ledger.reserve_action(ledger.start(ledger.create(Task(owner='builder',
            goal='Repair the existing fixture until real build and independent browser checks pass without weakening requested behavior.',
            inputs={'original_request':fixture['request'],'mode':'repair_build'},required_checks=['isolated_build']),action_limit=action_limit)),'builder')
        initial=build_evidence(WorkspaceTools(ledger,state,root,draft,workspace_boundary=boundary,check_runner=check))
        initial_report=json.loads(Path(initial[0].report).read_text(encoding='utf-8'))
        summary['initial_report']=initial[0].report
        if initial[0].exit_code==0 or not any(row['name']==fixture['initial_failure'] and row['exit_code'] not in {None,0}
            for row in initial_report.get('checks',{}).get('results',[])):
            raise RuntimeError('Expected initial failure was not observed; inspect environment and calibration evidence')
        if fixture['initial_failure']=='browser_acceptance':
            browser=json.loads(Path(initial_report['fixture_browser_report']).read_text(encoding='utf-8'))
            rows=browser.get('browser',{}).get('results',[])
            if (browser.get('error') or len(rows)!=len(CASES[name])
                or {row['name'] for row in rows}!=CASES[name]
                or not any(row.get('passed') is False for row in rows)):
                raise RuntimeError('Browser calibration did not execute the expected failing assertions; environment failure is not repair evidence')
        state=ledger.observe(state,Observation(revision=state.revision,fingerprint=initial[0].fingerprint,checks=initial))
        worker=SourceAgent(ledger,agent,root,draft,workspace_boundary=boundary,check_runner=check)
        reviewer=SeniorReviewer(agent,ledger,{'builder'},context_loader=lambda _:{'original_request':fixture['request'],
            'source':{path:safe_path(root,path).read_text(encoding='utf-8') for path in fixture['files']}},
            capabilities={'builder':'May edit declared source only; cannot change frozen browser assertions, dependencies or requirements.'})
        state=TaskCoordinator(ledger,{'builder':worker},reviewer,lambda:source_fingerprint(root)).run(state.task.id)
        summary.update(passed=state.status=='completed',status=state.status,task_id=state.task.id,
            dispatches=state.actions_used,pause_reason=state.pause_reason,final_report=state.observations[-1].checks[0].report if state.observations[-1].checks else None)
    except Exception as exc:summary['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if root.exists():
            target=root.resolve()
            if target.parent!=boundary.resolve() or not re.fullmatch(r'[a-f0-9]{32}',target.name):
                summary['cleanup_errors'].append('Fixture cleanup boundary failed')
            else:
                try:
                    shutil.copytree(target,directory/'source');summary['source_fingerprint']=source_fingerprint(directory/'source')
                    shutil.rmtree(target)
                except Exception as exc:summary['cleanup_errors'].append(str(exc))
        summary['model_calls']=len(list((directory/'model-calls').glob('*.json')))
        (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        (directory/'job.json').write_text(json.dumps(store.read(job),indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)
    return bool(summary['passed'] and not summary['cleanup_errors'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=sorted(FIXTURES),action='append')
    parser.add_argument('--actions',type=int,default=12)
    args=parser.parse_args()
    if args.actions<2:parser.error('--actions must allow initial verification and at least one repair')
    directory=PROJECT/'artifacts/repair-regressions'/uuid4().hex
    print('Evidence: '+str(directory),flush=True)
    passed=True
    for name in dict.fromkeys(args.case or FIXTURES):passed=evaluate(directory/name,name,args.actions) and passed
    return int(not passed)


if __name__=='__main__':raise SystemExit(main())
