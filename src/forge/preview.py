import json
import hashlib
import subprocess
import time
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen
from uuid import uuid4

from forge.builders import PROJECT
from forge.security import functional_evidence, security_gate
from forge.verification import bounded_command
from forge.workspace import safe_path


def check_preview_gate(record, root):
    from forge.browser_testing import browser_gate
    if record['status'] not in {'SECURITY_PASSED','PREVIEW_STOPPED','PREVIEW_FAILED'}:
        raise ValueError('Preview requires completed security gates and no active preview')
    fingerprint=functional_evidence(record,root)
    if not browser_gate(record,fingerprint):raise ValueError('Automated browser evidence is missing, stale or failed; rerun browser checks before preview')
    evidence=next((e['payload'] for e in reversed(record['events']) if e['status']=='SECURITY_PASSED'),None)
    if not evidence or evidence['source_fingerprint']!=fingerprint:
        raise ValueError('Security evidence does not match current source')
    report=json.loads(open(evidence['report'],encoding='utf-8').read())
    if report['source_fingerprint']!=fingerprint or not security_gate(report['checks'],report.get('source_unchanged',False)):
        raise ValueError('Required security checks are incomplete or blocked')
    lock_hash=hashlib.sha256((PROJECT/'requirements.lock.txt').read_bytes()).hexdigest()
    if report['checks'].get('pip_audit',{}).get('lock_sha256')!=lock_hash:
        raise ValueError('Python dependencies changed after the audit. Refresh security checks before preview.')
    return fingerprint


def docker(*args):
    return subprocess.check_output(['docker',*args],stderr=subprocess.STDOUT,text=True,timeout=30).strip()


def preview_resources(record):
    return next((e['payload']['preview'] for e in reversed(record['events'])
        if e['status'] in {'PREVIEW_STARTING','PREVIEW_RUNNING','PREVIEW_FAILED','PREVIEW_STOPPED'}
        and isinstance(e['payload'].get('preview'),dict)),None)


def cleanup(resources,job_id):
    for kind,key in [('container','proxy'),('container','container'),('network','network'),('network','ingress')]:
        name=resources.get(key)
        if not name:continue
        if not name.startswith('forge-preview-'):raise ValueError('Invalid preview resource identity')
        try:
            info=json.loads(docker(kind,'inspect',name))[0]
        except subprocess.CalledProcessError:continue
        labels=info.get('Config',{}).get('Labels',{}) if kind=='container' else info.get('Labels',{})
        if labels.get('forge.job')!=job_id or labels.get('forge.role')!='preview':
            raise ValueError('Refusing to remove an unrelated Docker resource')
        try:
            if kind=='container':docker('rm','--force',name)
            else:docker('network','rm',name)
        except subprocess.CalledProcessError as exc:
            # A simultaneous status/expiry cleanup may have removed the owned resource.
            if f'No such {kind}: {name}' not in str(exc.output):raise


def start_preview(job_id,store,approved=False,actor='local_cli'):
    if approved is not True:raise ValueError('Explicit local preview approval is required')
    record=store.read(job_id);root=PROJECT/'workspace'/job_id
    safe_path(root,'package.json')
    fingerprint=check_preview_gate(record,root)
    verified=next(e['payload'] for e in reversed(record['events']) if e['status']=='FUNCTIONALLY_VERIFIED')
    functional=json.loads(open(verified['report'],encoding='utf-8').read())
    image=functional['image']
    suffix=uuid4().hex[:12]
    resources={'container':'forge-preview-'+suffix,'network':'forge-preview-net-'+suffix,
               'proxy':'forge-preview-proxy-'+suffix,'ingress':'forge-preview-ingress-'+suffix}
    store.event(job_id,'PREVIEW_STARTING',{'preview':resources,'source_fingerprint':fingerprint,'approved_by':actor})
    try:
        docker('network','create','--internal','--label',f'forge.job={job_id}','--label','forge.role=preview',resources['network'])
        args=['docker','run','--detach','--rm','--name',resources['container'],'--pull=never',
              '--log-driver','local','--log-opt','max-size=5m','--log-opt','max-file=2',
              '--label',f'forge.job={job_id}','--label','forge.role=preview',
              '--network',resources['network'],
              '--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--user=1000:1000',
              '--memory=6g','--cpus=4','--pids-limit=256',
              '--tmpfs','/tmp:rw,noexec,nosuid,size=256m,uid=1000,gid=1000',
              '--tmpfs','/work:rw,nosuid,size=2g,uid=1000,gid=1000',
              '--mount',f'type=bind,source={root},target=/source,readonly',
              '--mount',f'type=bind,source={PROJECT / "tests/acceptance"},target=/trusted,readonly',
              '--workdir','/work','--env','NEXT_TELEMETRY_DISABLED=1','--env','SQLITE_PATH=/work/data/tasks.sqlite3',
              image,'/bin/sh','-c','cp -R /source/. /work/ && ln -s /opt/forge-deps/node_modules /work/node_modules && node /trusted/preview.mjs']
        execution=bounded_command(args,timeout=45)
        if execution['exit_code']!=0 or execution['stopped']:raise RuntimeError(execution['output'])
        docker('network','create','--label',f'forge.job={job_id}','--label','forge.role=preview',resources['ingress'])
        proxy_args=['docker','run','--detach','--rm','--name',resources['proxy'],'--pull=never',
                    '--log-driver','local','--log-opt','max-size=5m','--log-opt','max-file=2',
                    '--label',f'forge.job={job_id}','--label','forge.role=preview',
                    '--network',resources['ingress'],'--publish','127.0.0.1::3000',
                    '--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
                    '--user=1000:1000','--memory=128m','--cpus=1','--pids-limit=32',
                    '--env',f'APP_HOST={resources["container"]}',
                    '--mount',f'type=bind,source={PROJECT / "tests/acceptance/proxy.mjs"},target=/proxy.mjs,readonly',
                    'node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c',
                    'node','/proxy.mjs']
        execution=bounded_command(proxy_args,timeout=45)
        if execution['exit_code']!=0 or execution['stopped']:raise RuntimeError(execution['output'])
        docker('network','connect',resources['network'],resources['proxy'])
        info=json.loads(docker('inspect',resources['proxy']))[0]
        mapping=info['NetworkSettings']['Ports']['3000/tcp'][0]
        if mapping['HostIp']!='127.0.0.1':raise ValueError('Preview is not localhost-bound')
        url='http://127.0.0.1:'+mapping['HostPort']
        ready=False
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            try:
                with urlopen(url+'/api/health',timeout=2) as response:
                    ready=response.status==200
                if ready:break
            except Exception:time.sleep(1)
        if not ready:raise RuntimeError('Preview did not become healthy within 180 seconds')
        smoke={}
        review=next((e['payload'] for e in reversed(record['events']) if e['status']=='PLAN_REVIEW'),{})
        routes=review.get('requirements',{}).get('pages',['/']) if review.get('requirements',{}).get('spec_version')==2 else ['/','/api/tasks']
        for route in routes:
            with urlopen(url+route,timeout=5) as response:smoke[route]=response.status
        if not all(status==200 for status in smoke.values()):raise RuntimeError('Preview smoke test failed')
        info=json.loads(docker('inspect',resources['container']))[0]
        expires=(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()
        directory=PROJECT/'artifacts/preview'/job_id;directory.mkdir(parents=True,exist_ok=True)
        log_path=directory/(suffix+'.log')
        log_path.write_text(docker('logs','--tail','100',resources['container']),encoding='utf-8')
        store.event(job_id,'PREVIEW_RUNNING',{'preview':resources,'url':url,'source_fingerprint':fingerprint,
                    'container_id':info['Id'],'container_pid':info['State']['Pid'],'expires_no_later_than':expires,
                    'smoke_tests':smoke,'startup_logs':str(log_path),'data':'Disposable preview database; removed on stop/expiry'})
    except Exception as exc:
        try:cleanup(resources,job_id)
        except Exception:pass
        store.event(job_id,'PREVIEW_FAILED',{'reason':str(exc)[:2000],'preview':resources})
    return store.read(job_id)


def stop_preview(job_id,store):
    record=store.read(job_id);resources=preview_resources(record)
    if not resources:raise ValueError('No preview resources recorded')
    cleanup(resources,job_id)
    store.event(job_id,'PREVIEW_STOPPED',{'preview':resources})
    return store.read(job_id)


def preview_status(job_id,store):
    record=store.read(job_id)
    if record['status'] in {'PREVIEW_STARTING','PREVIEW_RUNNING'}:
        resources=preview_resources(record)
        try:
            for key in ('container','proxy'):
                if key not in resources:continue
                info=json.loads(docker('inspect',resources[key]))[0]
                if not info['State']['Running']:raise ValueError('Preview exited')
        except (subprocess.CalledProcessError,ValueError):
            return stop_preview(job_id,store)
    return record
