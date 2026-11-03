"""Run app-agnostic build checks in the existing dependency image."""
import hashlib
import json
import re
import subprocess
from pathlib import Path
from uuid import uuid4

from forge.verification import bounded_command
from forge.workspace import safe_path,source_fingerprint


PROJECT=Path(__file__).resolve().parents[2]


def harness_fingerprint():
    return hashlib.sha256((PROJECT/'tests/acceptance/source-checks.mjs').read_bytes()+b'\0'+
        (PROJECT/'tests/acceptance/framework-diagnostics.mjs').read_bytes()).hexdigest()


def run_source_checks(root,directory,job_id):
    if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise ValueError('Invalid job identity')
    root=Path(root).absolute();directory=Path(directory)
    safe_path(root,'package.json');safe_path(root,'package-lock.json')
    if not root.is_dir():raise ValueError('Application workspace is missing')
    directory.mkdir(parents=True,exist_ok=True)
    name='forge-check-'+uuid4().hex[:12]
    harness=PROJECT/'tests/acceptance/source-checks.mjs'
    diagnostics=PROJECT/'tests/acceptance/framework-diagnostics.mjs'
    fingerprint=source_fingerprint(root)
    report={'job_id':job_id,'source_fingerprint':fingerprint,'container':name,
        'harness_fingerprint':harness_fingerprint(),
        'coverage':{'typecheck':'NOT_RUN','production_build':'NOT_RUN','application_behavior':'NOT_TESTED'},
        'cleanup_errors':[],'passed':False}
    attempted=False
    try:
        inspection=['docker','image','inspect','forge-task-deps:local','--format','{{.Id}}']
        report['image_inspection_command']=inspection
        image=subprocess.check_output(inspection,stderr=subprocess.STDOUT,text=True,timeout=15).strip()
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('Dependency image did not resolve to an immutable image ID')
        report['image']=image
        args=['docker','run','--rm','--name',name,'--pull=never','--network=none',
            '--label',f'forge.job={job_id}','--label','forge.role=verification',
            '--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
            '--memory=6g','--cpus=4','--pids-limit=256','--user=1000:1000',
            '--tmpfs','/tmp:rw,noexec,nosuid,size=256m,uid=1000,gid=1000',
            '--tmpfs','/work:rw,nosuid,size=2g,uid=1000,gid=1000',
            '--mount',f'type=bind,source={root},target=/source,readonly',
            '--mount',f'type=bind,source={harness},target=/trusted/source-checks.mjs,readonly',
            '--mount',f'type=bind,source={diagnostics},target=/trusted/framework-diagnostics.mjs,readonly',
            '--workdir','/work','--env','NEXT_TELEMETRY_DISABLED=1','--env','SQLITE_PATH=/work/data/app.sqlite3',image,'/bin/sh','-c',
            'cp -R /source/. /work/ && ln -s /opt/forge-deps/node_modules /work/node_modules && node /trusted/source-checks.mjs']
        attempted=True;report['execution']=bounded_command(args,timeout=540)
        lines=[line.removeprefix('FORGE_SOURCE_REPORT:') for line in report['execution']['output'].splitlines() if line.startswith('FORGE_SOURCE_REPORT:')]
        if lines:report['checks']=json.loads(lines[-1])
        rows=report.get('checks',{}).get('results',[])
        for row in rows:
            if row['name'] in {'typecheck','production_build'}:
                report['coverage'][row['name']]='PASSED' if row['exit_code']==0 and not row.get('stopped') else 'FAILED'
        report['source_unchanged']=source_fingerprint(root)==fingerprint
        report['harness_unchanged']=harness_fingerprint()==report['harness_fingerprint']
        lock=report.get('checks',{}).get('source_lock')
        report['passed']=(report['execution']['exit_code']==0 and not report['execution']['stopped']
            and report.get('checks',{}).get('passed') is True and report['source_unchanged'] and report['harness_unchanged']
            and len(rows)==2 and {row['name'] for row in rows}=={'typecheck','production_build'}
            and all(row['exit_code']==0 and not row.get('stopped') for row in rows)
            and isinstance(lock,str) and re.fullmatch(r'[a-f0-9]{64}',lock) is not None
            and lock==report.get('checks',{}).get('image_lock'))
    except Exception as exc:
        report['error']=f'{type(exc).__name__}: {exc}'[:2000]
        if isinstance(exc,subprocess.CalledProcessError):
            report['environment_failure']={'command':exc.cmd,'exit_code':exc.returncode,'output':str(exc.output)[:4000]}
    finally:
        if attempted:
            try:
                cleanup=subprocess.run(['docker','rm','--force',name],capture_output=True,text=True,timeout=20)
                missing='No such container' in cleanup.stderr or 'No such container' in cleanup.stdout
                if cleanup.returncode and not missing:report['cleanup_errors'].append(cleanup.stderr[:1000])
            except Exception as exc:report['cleanup_errors'].append(str(exc)[:1000])
    if report['cleanup_errors']:report['passed']=False
    path=directory/(uuid4().hex+'.json');report['report']=str(path.resolve())
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
