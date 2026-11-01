"""Controller-owned browser profiles, executed separately from generated app code."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4

from forge.builders import PROJECT
from forge.workspace import safe_path, source_fingerprint
from forge.verification import bounded_command

PROFILE = 'temperature-converter-v1'
CASES = {'celsius_to_fahrenheit', 'fahrenheit_to_celsius', 'negative_and_decimal_values',
         'source_unit_does_not_relabel_result', 'changed_value_clears_previous_result',
         'empty_input_blocks_submission', 'extra_decimal_precision', 'mocked_api_error_is_visible'}


def profile_for(record):
    review=next((e['payload'] for e in reversed(record['events']) if e['status']=='PLAN_REVIEW'),{})
    requirements=review.get('requirements',{});plan=review.get('plan',{})
    if (requirements.get('spec_version')==2 and requirements.get('database')=='none'
        and requirements.get('pages')==['/'] and not requirements.get('entities')
        and set(plan.get('routes',[]))=={'POST /api/convert'}
        and 'temperature' in requirements.get('title','').lower()):return PROFILE
    return None


def harness_fingerprint():
    directory=PROJECT/'tests/browser'
    return hashlib.sha256(b''.join(name.encode()+b'\0'+(directory/name).read_bytes()
        for name in ['run.mjs','app-server.mjs','package-lock.json','Dockerfile'])).hexdigest()


def passed_report(report):
    rows=report.get('browser',{}).get('results',[])
    return (report.get('profile')==PROFILE and report.get('source_unchanged') is True
            and report.get('harness_fingerprint')==harness_fingerprint()
            and report.get('execution',{}).get('exit_code')==0
            and not report.get('execution',{}).get('stopped')
            and report.get('browser',{}).get('passed') is True
            and len(rows)==len(CASES) and {row.get('name') for row in rows}==CASES
            and all(row.get('passed') is True for row in rows)
            and not report.get('cleanup_errors'))


def browser_gate(record,fingerprint):
    evidence=next((e for e in reversed(record['events']) if e['status'] in {
        'AUTOMATED_BROWSER_STARTED','AUTOMATED_BROWSER_PASSED','AUTOMATED_BROWSER_FAILED'}
        and e['payload'].get('source_fingerprint')==fingerprint),None)
    if evidence is None:
        # Once a run opts into browser checks, changed source needs fresh evidence.
        return not any(e['status'] in {'AUTOMATED_BROWSER_STARTED','AUTOMATED_BROWSER_PASSED','AUTOMATED_BROWSER_FAILED'} for e in record['events'])
    if evidence['status']!='AUTOMATED_BROWSER_PASSED':return False
    try:
        report=json.loads(Path(evidence['payload']['report']).read_text(encoding='utf-8'))
        verified=next((e['payload'] for e in reversed(record['events']) if e['status']=='FUNCTIONALLY_VERIFIED'
                       and e['payload'].get('source_fingerprint')==fingerprint and e['payload'].get('report')),None)
        if verified:
            image=json.loads(Path(verified['report']).read_text(encoding='utf-8'))['image']
            if report.get('app_image')!=image:return False
        return report['source_fingerprint']==fingerprint and passed_report(report)
    except (OSError,ValueError,KeyError,TypeError):return False


def docker(*args):
    return subprocess.check_output(['docker',*args],stderr=subprocess.STDOUT,text=True,timeout=30).strip()


def missing_resource(error,kind,name):
    message=str(error.output)
    return any(marker in message for marker in [f'No such {kind}: {name}',f'{kind} {name} not found'])


def cleanup_browser(resources,job_id):
    for kind,key in [('container','browser'),('container','app'),('network','network')]:
        name=resources[key]
        if not re.fullmatch(r'forge-browser-(?:app|check|net)-[a-f0-9]{12}',name):raise ValueError('Invalid browser resource name')
        try:info=json.loads(docker(kind,'inspect',name))[0]
        except subprocess.CalledProcessError as exc:
            if missing_resource(exc,kind,name):continue
            raise
        labels=info.get('Config',{}).get('Labels',{}) if kind=='container' else info.get('Labels',{})
        if labels.get('forge.job')!=job_id or labels.get('forge.role')!='browser_verification':
            raise ValueError('Refusing to remove an unrelated browser resource')
        try:docker('rm','--force',name) if kind=='container' else docker('network','rm',name)
        except subprocess.CalledProcessError as exc:
            if not missing_resource(exc,kind,name):raise


def run_browser_checks(root,directory,job_id,*,on_start=None,app_image=None):
    if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise ValueError('Invalid browser job identity')
    if app_image is not None and not re.fullmatch(r'sha256:[a-f0-9]{64}',app_image):raise ValueError('Browser app image must be an immutable verified image ID')
    safe_path(root,'package.json')
    directory=Path(directory).resolve()
    if not directory.is_relative_to((PROJECT/'artifacts').resolve()):raise ValueError('Browser output must stay in artifacts')
    directory.mkdir(parents=True,exist_ok=True);output=directory/'results';output.mkdir()
    fingerprint=source_fingerprint(root);suffix=uuid4().hex[:12]
    resources={'app':'forge-browser-app-'+suffix,'browser':'forge-browser-check-'+suffix,'network':'forge-browser-net-'+suffix}
    report={'profile':PROFILE,'source_fingerprint':fingerprint,'harness_fingerprint':harness_fingerprint(),
            'resources':resources,'source_directory':str(root),'passed':False}
    if on_start:on_start(resources,fingerprint)
    labels=['--label',f'forge.job={job_id}','--label','forge.role=browser_verification']
    try:
        report['app_image']=app_image or docker('image','inspect','forge-task-deps:local','--format','{{.Id}}')
        report['browser_image']=docker('image','inspect','forge-browser-deps:local','--format','{{.Id}}')
        docker('network','create','--internal',*labels,resources['network'])
        app=['docker','run','--detach','--rm','--name',resources['app'],'--pull=never',*labels,
             '--network',resources['network'],'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
             '--user=1000:1000','--memory=6g','--cpus=2','--pids-limit=256',
             '--log-driver','local','--log-opt','max-size=2m','--log-opt','max-file=2',
             '--tmpfs','/tmp:rw,noexec,nosuid,size=256m,uid=1000,gid=1000',
             '--tmpfs','/work:rw,nosuid,size=2g,uid=1000,gid=1000',
             '--mount',f'type=bind,source={root.resolve()},target=/source,readonly',
             '--mount',f'type=bind,source={PROJECT / "tests/browser"},target=/trusted,readonly',
             '--workdir','/work','--env','NEXT_TELEMETRY_DISABLED=1',report['app_image'],
             '/bin/sh','-c','cp -R /source/. /work/ && ln -s /opt/forge-deps/node_modules /work/node_modules && node /trusted/app-server.mjs']
        startup=bounded_command(app,timeout=40,output_limit=40000)
        if startup['exit_code']!=0 or startup['stopped']:raise RuntimeError(startup['output'])
        # Native Linux bind mounts retain host ownership; match the non-root
        # operator so browser evidence is writable without world-write permissions.
        browser_user=f'{os.getuid()}:{os.getgid()}' if hasattr(os,'getuid') and os.getuid()!=0 else '1000:1000'
        command=['docker','run','--rm','--name',resources['browser'],'--pull=never',*labels,
                 '--network',resources['network'],'--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
                 '--user='+browser_user,'--memory=2g','--cpus=2','--pids-limit=256',
                 '--tmpfs','/tmp:rw,nosuid,size=512m,uid=1000,gid=1000',
                 '--env',f'FORGE_BROWSER_BASE=http://{resources["app"]}:3000',
                 '--mount',f'type=bind,source={PROJECT / "tests/browser"},target=/trusted,readonly',
                 '--mount',f'type=bind,source={output},target=/results',
                 report['browser_image'],'node','/trusted/run.mjs']
        report['execution']=bounded_command(command,timeout=330,output_limit=100000)
        path=output/'browser.json'
        if path.stat().st_size>100000:raise ValueError('Browser result exceeds budget')
        report['browser']=json.loads(path.read_text(encoding='utf-8'))
        report['app_logs']=docker('logs','--tail','80',resources['app'])[-16000:]
    except Exception as exc:report['error']=str(exc)[-3000:]
    finally:
        try:cleanup_browser(resources,job_id)
        except Exception as exc:report['cleanup_errors']=str(exc)[-1000:]
    report['source_unchanged']=source_fingerprint(root)==fingerprint
    report['passed']=passed_report(report)
    path=directory/'report.json';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report,path


def browser_job(job_id,store):
    from forge.security import functional_evidence
    record=store.read(job_id)
    if not profile_for(record):raise ValueError('No trusted automated browser profile matches this reviewed app')
    if record['status']=='PREVIEW_RUNNING':
        from forge.preview import stop_preview
        record=stop_preview(job_id,store)
    if record['status'] not in {'FUNCTIONALLY_VERIFIED','SECURITY_PASSED','PREVIEW_STOPPED','PREVIEW_FAILED'}:
        raise ValueError('Browser checks require current functional verification')
    root=PROJECT/'workspace'/job_id;fingerprint=functional_evidence(record,root)
    verified=next(e['payload'] for e in reversed(record['events']) if e['status']=='FUNCTIONALLY_VERIFIED' and e['payload'].get('source_fingerprint')==fingerprint)
    app_image=json.loads(Path(verified['report']).read_text(encoding='utf-8'))['image']
    def started(resources,source):
        assert source==fingerprint
        store.event(job_id,'AUTOMATED_BROWSER_STARTED',{'profile':PROFILE,'resources':resources,'source_fingerprint':source},update_status=False)
    report,path=run_browser_checks(root,PROJECT/'artifacts/browser'/job_id/uuid4().hex,job_id,on_start=started,app_image=app_image)
    store.event(job_id,'AUTOMATED_BROWSER_PASSED' if report['passed'] else 'AUTOMATED_BROWSER_FAILED',
                {'profile':PROFILE,'source_fingerprint':fingerprint,'report':str(path),
                 'reason':None if report['passed'] else 'Automated browser checks did not pass. Inspect the report before preview.'},update_status=False)
    return store.read(job_id)
