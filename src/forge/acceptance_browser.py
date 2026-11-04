"""Run a frozen QA browser contract separately from generated application execution."""
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from forge.autonomous_acceptance import AcceptanceSuite
from forge.browser_testing import cleanup_browser,docker
from forge.source_checks import PROJECT
from forge.verification import bounded_command
from forge.workspace import safe_path,source_fingerprint


def harness_fingerprint():
    names=['src/forge/acceptance_browser.py','tests/acceptance/browser.mjs','tests/acceptance/browser-protocol.mjs',
        'tests/acceptance/browser-diagnostics.mjs',
        'tests/browser/app-server.mjs','tests/browser/package-lock.json','tests/browser/Dockerfile']
    return hashlib.sha256(b''.join(name.encode()+b'\0'+(PROJECT/name).read_bytes() for name in names)).hexdigest()


def read_contract(contract):
    path=Path(contract['report'])
    if path.stat().st_size>100000:raise ValueError('Acceptance contract exceeds budget')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=contract['fingerprint']:raise ValueError('Frozen acceptance contract changed')
    packet=json.loads(raw)
    for key in ['version','job_id','task_id','revision','review_fingerprint','model']:
        if packet.get(key)!=contract.get(key):raise ValueError('Acceptance contract identity changed')
    suite=AcceptanceSuite.model_validate(packet['suite'])
    if not suite.scenarios:raise ValueError('No executable acceptance scenarios; report unsupported coverage before execution')
    if len({case.id for case in suite.scenarios})!=len(suite.scenarios):raise ValueError('Duplicate acceptance scenario IDs')
    return suite


def _passed_report(report,contract,scenario_id=None):
    suite=read_contract(contract);rows=report.get('browser',{}).get('results',[])
    expected={case.id:case.criteria for case in suite.scenarios if scenario_id is None or case.id==scenario_id}
    if not expected:return False
    return bool(report.get('job_id')==contract['job_id'] and not report.get('error')
        and re.fullmatch(r'sha256:[a-f0-9]{64}',report.get('app_image',''))
        and re.fullmatch(r'sha256:[a-f0-9]{64}',report.get('browser_image',''))
        and report.get('contract_fingerprint')==contract['fingerprint']
        and report.get('review_fingerprint')==contract['review_fingerprint']
        and report.get('source_unchanged') is True and report.get('contract_unchanged') is True
        and report.get('harness_unchanged') is True and report.get('harness_fingerprint')==harness_fingerprint()
        and report.get('execution',{}).get('exit_code')==0 and not report['execution'].get('stopped')
        and report.get('browser',{}).get('passed') is True and len(rows)==len(expected)
        and {row.get('id') for row in rows}==set(expected)
        and all(row.get('passed') is True and row.get('criteria')==expected[row['id']] for row in rows)
        and not report.get('cleanup_errors'))


def passed_report(report,contract):
    if not _passed_report(report,contract):return False
    if 'scenario_reports' in report:
        expected={case.id for case in read_contract(contract).scenarios}
        references=report['scenario_reports']
        if len(references)!=len(expected) or {row['id'] for row in references}!=expected:return False
        for row in references:
            path=Path(row['report']).resolve()
            if not path.is_relative_to((PROJECT/'artifacts').resolve()) or path.stat().st_size>100000:return False
            raw=path.read_bytes();case=json.loads(raw)
            if hashlib.sha256(raw).hexdigest()!=row['sha256'] or not _passed_report(case,contract,row['id']):return False
            if any(case[key]!=report[key] for key in ['source_fingerprint','harness_fingerprint','app_image','browser_image']):return False
    return True


def _run_acceptance_browser(root,directory,job_id,contract,app_image,scenario_id=None):
    suite=read_contract(contract)
    if not re.fullmatch(r'[a-f0-9]{32}',job_id) or contract['job_id']!=job_id:raise ValueError('Invalid acceptance job identity')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',app_image):raise ValueError('Expected immutable verified app image')
    root=Path(root).absolute();safe_path(root,'package.json')
    directory=Path(directory).resolve()
    if not directory.is_relative_to((PROJECT/'artifacts').resolve()):raise ValueError('Acceptance output must stay in artifacts')
    directory.mkdir(parents=True,exist_ok=True);output=directory/'results';output.mkdir()
    suffix=uuid4().hex[:12]
    resources={'app':'forge-browser-app-'+suffix,'browser':'forge-browser-check-'+suffix,'network':'forge-browser-net-'+suffix}
    report={'version':1,'job_id':job_id,'phase':'started','resources':resources,'source_fingerprint':source_fingerprint(root),
        'contract_fingerprint':contract['fingerprint'],'review_fingerprint':contract['review_fingerprint'],
        'harness_fingerprint':harness_fingerprint(),'app_image':app_image,'passed':False,'cleanup_errors':[],
        'uncovered':suite.model_dump()['uncovered'],
        'scope':'Selected requirements-derived browser assertions only; database restart, security and deployment NOT_TESTED.'}
    path=directory/'report.json';report['report']=str(path);path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    labels=['--label',f'forge.job={job_id}','--label','forge.role=browser_verification']
    isolation=['--pull=never',*labels,'--network',resources['network'],'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges']
    try:
        report['browser_image']=docker('image','inspect','forge-browser-deps:local','--format','{{.Id}}')
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',report['browser_image']):raise ValueError('Browser image must be immutable')
        docker('network','create','--internal',*labels,resources['network'])
        app=['docker','run','--detach','--rm','--name',resources['app'],*isolation,
            '--user=1000:1000','--memory=6g','--cpus=2','--pids-limit=256',
            '--log-driver','local','--log-opt','max-size=2m','--log-opt','max-file=2',
            '--tmpfs','/tmp:rw,noexec,nosuid,size=256m,uid=1000,gid=1000','--tmpfs','/work:rw,nosuid,size=2g,uid=1000,gid=1000',
            '--mount',f'type=bind,source={root},target=/source,readonly',
            '--mount',f'type=bind,source={PROJECT/"tests/browser/app-server.mjs"},target=/trusted/app-server.mjs,readonly',
            '--workdir','/work','--env','NEXT_TELEMETRY_DISABLED=1','--env','SQLITE_PATH=/work/data/app.sqlite3',app_image,'/bin/sh','-c',
            'cp -R /source/. /work/ && ln -s /opt/forge-deps/node_modules /work/node_modules && node /trusted/app-server.mjs']
        report['startup']=bounded_command(app,timeout=40,output_limit=40000)
        if report['startup']['exit_code']!=0 or report['startup']['stopped']:raise RuntimeError(report['startup']['output'])
        user=f'{os.getuid()}:{os.getgid()}' if hasattr(os,'getuid') and os.getuid()!=0 else '1000:1000'
        command=['docker','run','--rm','--name',resources['browser'],*isolation,'--user='+user,
            '--memory=2g','--cpus=2','--pids-limit=256','--tmpfs','/tmp:rw,nosuid,size=512m,uid=1000,gid=1000',
            '--env',f'FORGE_BROWSER_BASE=http://{resources["app"]}:3000',
            '--mount',f'type=bind,source={PROJECT/"tests/acceptance/browser.mjs"},target=/trusted/browser.mjs,readonly',
            '--mount',f'type=bind,source={PROJECT/"tests/acceptance/browser-protocol.mjs"},target=/trusted/browser-protocol.mjs,readonly',
            '--mount',f'type=bind,source={PROJECT/"tests/acceptance/browser-diagnostics.mjs"},target=/trusted/browser-diagnostics.mjs,readonly',
            '--mount',f'type=bind,source={Path(contract["report"]).resolve()},target=/trusted/contract.json,readonly',
            '--mount',f'type=bind,source={output},target=/results',report['browser_image'],'node','/trusted/browser.mjs']
        if scenario_id is not None:
            command[2:2]=['--env',f'FORGE_SCENARIO_ID={scenario_id}']
        report['execution']=bounded_command(command,timeout=330,output_limit=64000)
        result=output/'browser.json'
        if result.stat().st_size>64000:raise ValueError('Browser result exceeds budget')
        report['browser']=json.loads(result.read_text(encoding='utf-8'))
    except Exception as exc:report['error']=str(exc)[-3000:]
    finally:
        try:cleanup_browser(resources,job_id)
        except Exception as exc:report['cleanup_errors'].append(str(exc)[-1000:])
    report['source_unchanged']=source_fingerprint(root)==report['source_fingerprint']
    report['harness_unchanged']=harness_fingerprint()==report['harness_fingerprint']
    try:read_contract(contract);report['contract_unchanged']=True
    except (ValueError,OSError,KeyError):report['contract_unchanged']=False
    try:report['passed']=_passed_report(report,contract,scenario_id)
    except (ValueError,OSError,KeyError):report['passed']=False
    report['phase']='completed';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def run_acceptance_browser(root,directory,job_id,contract,app_image):
    """Isolate durable application state between cases, preserving the frozen suite."""
    suite=read_contract(contract)
    if len(suite.scenarios)==1:return _run_acceptance_browser(root,directory,job_id,contract,app_image)
    directory=Path(directory).resolve()
    if not directory.is_relative_to((PROJECT/'artifacts').resolve()):raise ValueError('Acceptance output must stay in artifacts')
    directory.mkdir(parents=True,exist_ok=True)
    report={'version':1,'job_id':job_id,'source_fingerprint':source_fingerprint(Path(root)),
        'contract_fingerprint':contract['fingerprint'],'review_fingerprint':contract['review_fingerprint'],
        'harness_fingerprint':harness_fingerprint(),'app_image':app_image,'passed':False,
        'cleanup_errors':[],'scenario_reports':[],'uncovered':suite.model_dump()['uncovered'],
        'scope':'Fresh app process and temporary database per scenario; reload persistence within each scenario. Database restart, security and deployment NOT_TESTED.'}
    cases=[]
    try:
        for index,scenario in enumerate(suite.scenarios):
            case=_run_acceptance_browser(root,directory/f'scenario-{index}',job_id,contract,app_image,scenario.id)
            cases.append(case)
            report['scenario_reports'].append({'id':scenario.id,'report':case['report'],
                'sha256':hashlib.sha256(Path(case['report']).read_bytes()).hexdigest()})
        images={case.get('browser_image') for case in cases}
        if len(images)!=1 or None in images:raise ValueError('Scenario browser images do not match')
        report['browser_image']=next(iter(images))
        report['browser']={'passed':all(case['passed'] for case in cases),
            'results':[row for case in cases for row in case.get('browser',{}).get('results',[])]}
        report['execution']={'exit_code':0 if all(case['passed'] for case in cases) else 1,
            'stopped':next((case.get('execution',{}).get('stopped') for case in cases if case.get('execution',{}).get('stopped')),None)}
        errors=[case['error'] for case in cases if case.get('error')]
        if errors:report['error']='; '.join(errors)[:3000]
    except Exception as exc:report['error']=str(exc)[-3000:]
    report['cleanup_errors']=[error for case in cases for error in case.get('cleanup_errors',[])]
    report['source_unchanged']=source_fingerprint(Path(root))==report['source_fingerprint'] and all(case['source_unchanged'] and case['source_fingerprint']==report['source_fingerprint'] for case in cases)
    report['harness_unchanged']=harness_fingerprint()==report['harness_fingerprint'] and all(case['harness_unchanged'] and case['harness_fingerprint']==report['harness_fingerprint'] for case in cases)
    try:read_contract(contract);report['contract_unchanged']=all(case['contract_unchanged'] for case in cases)
    except (ValueError,OSError,KeyError):report['contract_unchanged']=False
    report['report']=str(directory/'report.json');report['phase']='completed'
    try:report['passed']=passed_report(report,contract)
    except (ValueError,OSError,KeyError,TypeError):report['passed']=False
    Path(report['report']).write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
