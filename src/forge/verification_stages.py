"""Build and document-startup evidence, distinct from requirements verification."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from forge.acceptance_browser import passed_smoke_report
from forge.source_checks import harness_fingerprint as build_harness
from forge.workspace import source_fingerprint


def startup_evidence_current(result,root,job_id):
    try:
        build_path=Path(result['build_report']);smoke_path=Path(result['smoke_report'])
        build=json.loads(build_path.read_bytes());smoke=json.loads(smoke_path.read_bytes())
        return bool(result['stage_protocol']==1
            and result['job_id']==build['job_id']==smoke['job_id']==job_id
            and result['source_fingerprint']==build['source_fingerprint']==smoke['source_fingerprint']==source_fingerprint(root)
            and result['image']==build['image']==smoke['app_image']
            and hashlib.sha256(build_path.read_bytes()).hexdigest()==result['build_report_sha256']
            and hashlib.sha256(smoke_path.read_bytes()).hexdigest()==result['smoke_report_sha256']
            and build['passed'] and build['harness_fingerprint']==build_harness()
            and passed_smoke_report(smoke))
    except (ValueError,OSError,KeyError,TypeError):return False


def check_startup(root,directory,job_id,check_runner,smoke_runner):
    result=check_runner(root,directory,job_id)
    if not result['passed']:return result
    build_path=Path(result['report'])
    smoke=smoke_runner(root,directory/('smoke-'+uuid4().hex),job_id,result['image'])
    failures=[row for row in smoke.get('browser',{}).get('results',[]) if row.get('passed') is not True]
    valid=bool(smoke.get('passed') and passed_smoke_report(smoke)
        and smoke.get('job_id')==job_id and smoke.get('source_fingerprint')==result['source_fingerprint']==source_fingerprint(root)
        and smoke.get('app_image')==result['image'])
    if smoke.get('error') or smoke.get('cleanup_errors'):
        result['environment_failure']={'stage':'browser_smoke','report':smoke['report'],
            'error':smoke.get('error'),'cleanup_errors':smoke.get('cleanup_errors',[])}
    elif smoke.get('passed') and not valid:
        result['environment_failure']={'stage':'browser_smoke','report':smoke['report'],
            'error':'Startup evidence failed source, image, job or harness validation. No application defect established.'}
    result['checks']['results'].append({'name':'browser_smoke','exit_code':0 if valid else 1,'stopped':None,
        'output':json.dumps({'failures':failures,'error':smoke.get('error'),'cleanup_errors':smoke.get('cleanup_errors',[])})})
    result.update(stage_protocol=1,build_report=str(build_path),smoke_report=smoke['report'],
        build_report_sha256=hashlib.sha256(build_path.read_bytes()).hexdigest(),
        smoke_report_sha256=hashlib.sha256(Path(smoke['report']).read_bytes()).hexdigest())
    result['cleanup_errors'].extend(smoke.get('cleanup_errors',[]))
    result['coverage'].update(document_smoke='PASSED' if valid else 'FAILED',application_behavior='UNVERIFIED')
    result['passed']=bool(valid and not result['cleanup_errors']);result['checks']['passed']=result['passed']
    path=directory/('startup-'+uuid4().hex+'.json');result['report']=str(path.resolve())
    path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
