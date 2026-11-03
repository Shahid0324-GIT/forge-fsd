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
    names=['tests/acceptance/browser.mjs','tests/acceptance/browser-protocol.mjs',
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


def passed_report(report,contract):
    suite=read_contract(contract);rows=report.get('browser',{}).get('results',[])
    expected={case.id:case.criteria for case in suite.scenarios}
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


def run_acceptance_browser(root,directory,job_id,contract,app_image):
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
            '--mount',f'type=bind,source={Path(contract["report"]).resolve()},target=/trusted/contract.json,readonly',
            '--mount',f'type=bind,source={output},target=/results',report['browser_image'],'node','/trusted/browser.mjs']
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
    try:report['passed']=passed_report(report,contract)
    except (ValueError,OSError,KeyError):report['passed']=False
    report['phase']='completed';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
