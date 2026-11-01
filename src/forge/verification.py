import json
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from forge.builders import PROJECT
from forge.workspace import source_fingerprint
from forge.schemas import RequirementsDocument,ImplementationPlan,validate_app_contract
from forge.workflow import review_fingerprint


def bounded_command(args, timeout=600, output_limit=400000):
    started = time.monotonic()
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = bytearray()
    exceeded = threading.Event()

    def collect():
        while chunk := process.stdout.read(4096):
            remaining = output_limit - len(output)
            output.extend(chunk[:remaining])
            if len(chunk) > remaining:
                exceeded.set()
                process.kill()
                break

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    stopped = None
    try:
        while process.poll() is None:
            if time.monotonic() - started > timeout:
                stopped = 'timeout'
                process.kill()
                break
            time.sleep(.1)
        process.wait(timeout=10)
    finally:
        reader.join(timeout=5)
    if exceeded.is_set():
        stopped = 'output_limit'
    return {"command": args, "exit_code": process.returncode, "stopped": stopped,
            "wall_seconds": round(time.monotonic()-started, 2), "output": output.decode('utf-8', errors='replace')}


def verify_job(job_id, store):
    record = store.read(job_id)
    if record['status'] not in {'GENERATED_UNVERIFIED', 'VERIFICATION_FAILED', 'FUNCTIONALLY_VERIFIED',
                                'SECURITY_BLOCKED','SECURITY_PASSED','PREVIEW_STOPPED'}:
        raise ValueError('Only generated or failed-verification jobs can be verified')
    root = PROJECT / 'workspace' / job_id
    fingerprint = source_fingerprint(root)
    name = 'forge-check-' + uuid4().hex[:12]
    report = {"job_id": job_id, "source_fingerprint": fingerprint,
              "timestamp": datetime.now(timezone.utc).isoformat()}
    contract=None
    review=next((e['payload'] for e in reversed(record['events']) if e['status']=='PLAN_REVIEW'),None)
    if review and review['requirements'].get('spec_version')==2:
        requirements=RequirementsDocument.model_validate(review['requirements'])
        plan=ImplementationPlan.model_validate(review['plan'])
        validate_app_contract(requirements,plan)
        approval=next((e['payload'] for e in reversed(record['events']) if e['status']=='APPROVED'),None)
        if not approval or approval['fingerprint']!=review_fingerprint(review['requirements'],review['plan']):
            raise ValueError('Verification requires the approved application contract')
        directory=PROJECT/'artifacts/verification'/job_id
        directory.mkdir(parents=True,exist_ok=True)
        contract=directory/(uuid4().hex+'-contract.json')
        contract.write_text(json.dumps({'requirements':requirements.model_dump(),'plan':plan.model_dump()}),encoding='utf-8')
        report['contract_sha256']=__import__('hashlib').sha256(contract.read_bytes()).hexdigest()
        report['coverage']={'http_scenarios':[s.name for s in requirements.scenarios],'browser_interactions':'NOT_TESTED',
                            'limitations':['Scenarios are model-proposed and human-approved; they are not a complete correctness specification.']}
    store.event(job_id, 'VERIFYING', {'source_fingerprint':fingerprint})
    # Resolve the mutable local dependency-image tag to its immutable image ID.
    try:
        image = subprocess.check_output(['docker','image','inspect','forge-task-deps:local','--format','{{.Id}}'],text=True,timeout=15).strip()
        report['image'] = image
        args = ['docker','run','--rm','--name',name,'--pull=never','--network=none',
                '--label',f'forge.job={job_id}','--label','forge.role=verification',
                '--read-only','--cap-drop=ALL','--security-opt=no-new-privileges',
                '--memory=6g','--cpus=4','--pids-limit=256','--user=1000:1000',
                '--tmpfs','/tmp:rw,noexec,nosuid,size=256m,uid=1000,gid=1000',
                '--tmpfs','/work:rw,nosuid,size=2g,uid=1000,gid=1000',
                '--mount',f'type=bind,source={root},target=/source,readonly',
                '--mount',f'type=bind,source={PROJECT / "tests" / "acceptance"},target=/trusted,readonly',
                '--workdir','/work','--env','NEXT_TELEMETRY_DISABLED=1',
                '--env','SQLITE_PATH=/work/data/tasks.sqlite3',
                image,'/bin/sh','-c',
                'cp -R /source/. /work/ && ln -s /opt/forge-deps/node_modules /work/node_modules && node /trusted/verify.mjs']
        if contract:
            args[args.index('--workdir'):args.index('--workdir')]=['--mount',f'type=bind,source={contract},target=/contract.json,readonly','--env','FORGE_APP_CONTRACT=/contract.json']
        report['execution'] = bounded_command(args)
        lines = [line.removeprefix('FORGE_REPORT:') for line in report['execution']['output'].splitlines() if line.startswith('FORGE_REPORT:')]
        if lines:
            report['checks'] = json.loads(lines[-1])
        report['source_unchanged'] = source_fingerprint(root) == fingerprint
        passed = report['execution']['exit_code'] == 0 and not report['execution']['stopped'] and report.get('checks',{}).get('passed') is True and report['source_unchanged']
    except Exception as exc:
        report['error'] = str(exc)[:2000]
        passed = False
    finally:
        subprocess.run(['docker','rm','--force',name],capture_output=True,timeout=20)
    directory = PROJECT / 'artifacts' / 'verification' / job_id
    directory.mkdir(parents=True,exist_ok=True)
    path = directory / (uuid4().hex + '.json')
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    store.event(job_id, 'FUNCTIONALLY_VERIFIED' if passed else 'VERIFICATION_FAILED',
                {'source_fingerprint':fingerprint,'report':str(path),'security':'UNVERIFIED'})
    return store.read(job_id)
