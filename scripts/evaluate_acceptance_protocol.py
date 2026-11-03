"""Calibrate generic browser execution on correct/incorrect controller-authored fixtures."""
import hashlib
import json
import re
import shutil
from uuid import uuid4

from forge.acceptance_browser import run_acceptance_browser
from forge.source_checks import PROJECT,run_source_checks
from forge.workspace import seed_workspace,source_fingerprint


def evaluate(directory,increment):
    job=uuid4().hex;boundary=PROJECT/'workspace/.acceptance-fixtures';root=boundary/job
    directory.mkdir(parents=True)
    summary={'job_id':job,'increment':increment,'passed':False,'cleanup_errors':[],
        'scope':'Controller-authored runner calibration, not agent-generated acceptance or app generation.'}
    try:
        seed_workspace(PROJECT/'templates/task-app',root,generic=True)
        (root/'app/page.tsx').write_text("'use client';\nimport {useState} from 'react';\nexport default function Page(){const [n,setN]=useState(0);return <main><output>Count: {n}</output><button onClick={()=>setN(n+"+str(increment)+")}>Increment</button></main>}\n",encoding='utf-8')
        packet={'version':1,'job_id':job,'task_id':uuid4().hex,'revision':1,'model':'controller_fixture',
            'review_fingerprint':'a'*64,'suite':{'scenarios':[{'id':'increments','criteria':[1],'steps':[
                {'action':'visit','path':'/'},
                {'action':'assert_visible','target':{'by':'text','value':'Count: 0','name':''}},
                {'action':'click','target':{'by':'role','value':'button','name':'Increment'}},
                {'action':'assert_visible','target':{'by':'text','value':'Count: 1','name':''}},
                {'action':'click','target':{'by':'role','value':'button','name':'Increment'}},
                {'action':'assert_visible','target':{'by':'text','value':'Count: 2','name':''}},
            ]}],'uncovered':[]}}
        path=directory/'contract.json';path.write_text(json.dumps(packet,indent=2),encoding='utf-8')
        contract={**packet,'fingerprint':hashlib.sha256(path.read_bytes()).hexdigest(),'report':str(path)}
        build=run_source_checks(root,directory/'build',job);summary['build_report']=build['report']
        if not build['passed']:raise RuntimeError('Calibration app did not pass build checks')
        browser=run_acceptance_browser(root,directory/'browser',job,contract,build['image'])
        summary['browser_report']=browser['report'];summary['cleanup_errors'].extend(browser['cleanup_errors'])
        rows=browser.get('browser',{}).get('results',[])
        summary['passed']=bool(browser['passed'] if increment==1 else not browser.get('error') and len(rows)==1
            and rows[0].get('id')=='increments' and rows[0].get('passed') is False and rows[0].get('step')==4
            and 'Count: 2' in rows[0].get('page_text','') and not rows[0].get('runtime_errors'))
    except Exception as exc:summary['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if root.exists():
            target=root.resolve()
            if target.parent!=boundary.resolve() or not re.fullmatch(r'[a-f0-9]{32}',target.name):
                summary['cleanup_errors'].append('Fixture cleanup boundary failed')
            else:
                shutil.copytree(target,directory/'source');summary['source_fingerprint']=source_fingerprint(directory/'source')
                shutil.rmtree(target)
        summary['passed']=bool(summary['passed'] and not summary['cleanup_errors'])
        (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)
    return summary['passed']


def main():
    directory=PROJECT/'artifacts/acceptance-calibration'/uuid4().hex
    print('Evidence: '+str(directory),flush=True)
    correct=evaluate(directory/'correct',1)
    incorrect=evaluate(directory/'incorrect',2)
    return int(not (correct and incorrect))


if __name__=='__main__':raise SystemExit(main())
