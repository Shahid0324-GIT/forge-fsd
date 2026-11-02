"""Isolated browser checks for two frozen evaluation fixtures, not a general app gate."""
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

from forge.browser_testing import cleanup_browser,docker
from forge.source_checks import PROJECT
from forge.verification import bounded_command
from forge.workspace import safe_path,source_fingerprint


CASES={'counter':{'starts_at_zero','increments_by_one'},'formatter':{'uppercases_name','trims_whitespace'},
    'client-boundary':{'starts_at_zero','increments_by_one','resets_to_zero','preserves_metadata'}}


def harness_fingerprint():
    files=['tests/repair/browser.mjs','tests/browser/app-server.mjs','tests/browser/package-lock.json','tests/browser/Dockerfile']
    return hashlib.sha256(b''.join(name.encode()+b'\0'+(PROJECT/name).read_bytes() for name in files)).hexdigest()


def passed_report(report):
    rows=report.get('browser',{}).get('results',[])
    expected=CASES.get(report.get('fixture'))
    return bool(expected and report.get('source_unchanged') is True and report.get('harness_unchanged') is True
        and report.get('harness_fingerprint')==harness_fingerprint()
        and report.get('execution',{}).get('exit_code')==0 and not report['execution'].get('stopped')
        and report.get('browser',{}).get('fixture')==report['fixture'] and report['browser'].get('passed') is True
        and len(rows)==len(expected) and {row.get('name') for row in rows}==expected
        and all(row.get('passed') is True for row in rows) and not report.get('cleanup_errors'))


def run_fixture_browser(root,directory,job_id,fixture,app_image):
    if fixture not in CASES:raise ValueError('Unknown frozen repair fixture')
    if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise ValueError('Invalid fixture job identity')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',app_image):raise ValueError('Expected immutable verified app image')
    root=Path(root).absolute();safe_path(root,'package.json')
    directory=Path(directory).resolve()
    if not directory.is_relative_to((PROJECT/'artifacts').resolve()):raise ValueError('Fixture browser output must stay in artifacts')
    directory.mkdir(parents=True,exist_ok=True);output=directory/'results';output.mkdir()
    suffix=uuid4().hex[:12]
    resources={'app':'forge-browser-app-'+suffix,'browser':'forge-browser-check-'+suffix,'network':'forge-browser-net-'+suffix}
    report={'fixture':fixture,'job_id':job_id,'phase':'started','source_fingerprint':source_fingerprint(root),'harness_fingerprint':harness_fingerprint(),
        'resources':resources,'app_image':app_image,'passed':False,'cleanup_errors':[],
        'scope':'Frozen fixture browser assertions only; not general generated-app readiness.'}
    path=directory/'report.json';report['report']=str(path)
    # Keep resource identities discoverable even if the operator process exits.
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
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
            '--mount',f'type=bind,source={PROJECT / "tests/browser/app-server.mjs"},target=/trusted/app-server.mjs,readonly',
            '--workdir','/work','--env','NEXT_TELEMETRY_DISABLED=1',app_image,'/bin/sh','-c',
            'cp -R /source/. /work/ && ln -s /opt/forge-deps/node_modules /work/node_modules && node /trusted/app-server.mjs']
        report['startup']=bounded_command(app,timeout=40,output_limit=40000)
        if report['startup']['exit_code']!=0 or report['startup']['stopped']:raise RuntimeError(report['startup']['output'])
        user=f'{os.getuid()}:{os.getgid()}' if hasattr(os,'getuid') and os.getuid()!=0 else '1000:1000'
        command=['docker','run','--rm','--name',resources['browser'],*isolation,
            '--user='+user,'--memory=2g','--cpus=2','--pids-limit=256',
            '--tmpfs','/tmp:rw,nosuid,size=512m,uid=1000,gid=1000','--env',f'FORGE_BROWSER_BASE=http://{resources["app"]}:3000',
            '--mount',f'type=bind,source={PROJECT / "tests/repair/browser.mjs"},target=/trusted/browser.mjs,readonly',
            '--mount',f'type=bind,source={output},target=/results',report['browser_image'],'node','/trusted/browser.mjs',fixture]
        report['execution']=bounded_command(command,timeout=210,output_limit=64000)
        result=output/'browser.json'
        if result.stat().st_size>64000:raise ValueError('Fixture browser result exceeds budget')
        report['browser']=json.loads(result.read_text(encoding='utf-8'))
    except Exception as exc:report['error']=str(exc)[-3000:]
    finally:
        try:cleanup_browser(resources,job_id)
        except Exception as exc:report['cleanup_errors'].append(str(exc)[-1000:])
    report['source_unchanged']=source_fingerprint(root)==report['source_fingerprint']
    report['harness_unchanged']=harness_fingerprint()==report['harness_fingerprint']
    report['passed']=passed_report(report)
    report['phase']='completed'
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
