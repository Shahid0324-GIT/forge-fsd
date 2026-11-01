"""One managed operation per subprocess, separate from HTTP/SSE request lifetimes."""
import argparse
import json
from pathlib import Path

from forge.agents import OllamaAgents
from forge.models import job_model
from forge.builders import build_job
from forge.persistence import JobStore
from forge.preview import preview_status, start_preview, stop_preview
from forge.repair import repair_job
from forge.reporting import write_report
from forge.security import security_job
from forge.verification import verify_job
from forge.workflow import invoke_job, resume_job,retry_planning


def pipeline(job_id,agents,store):
    record=store.read(job_id)
    if record['status']=='APPROVED':record=build_job(job_id,agents,store)
    if record['status']=='GENERATED_UNVERIFIED':record=verify_job(job_id,store)
    while record['status']=='VERIFICATION_FAILED':
        attempts=sum(e['status']=='REPAIRING' for e in record['events'])
        if attempts>=2:break
        try:record=repair_job(job_id,agents,store)
        except ValueError as exc:
            store.event(job_id,'REPAIR_REVIEW_REQUIRED',{'reason':str(exc)},update_status=False)
            break
        if record['status']=='GENERATED_UNVERIFIED':record=verify_job(job_id,store)
        else:break
    if record['status'] in {'FUNCTIONALLY_VERIFIED','SECURITY_BLOCKED'}:
        record=security_job(job_id,agents,store)
    if record['status']=='SECURITY_PASSED':record=write_report(job_id,agents,store)
    return record


def execute(job_id,action,payload,store,agents):
    if action=='browser_check':
        from forge.browser_testing import browser_job
        return browser_job(job_id,store)
    if action=='retry_build':
        record=build_job(job_id,agents,store,resume=True)
        return pipeline(job_id,agents,store) if record['status']=='GENERATED_UNVERIFIED' else record
    if action=='retry_plan':return retry_planning(job_id,agents,store)
    if action=='plan':
        return invoke_job(job_id,{'job_id':job_id,'description':payload['description'],'calls':0,'rounds':0},agents,store)
    if action=='answer':return resume_job(job_id,{'answers':payload['answers']},agents,store)
    if action in {'approve','reject'}:
        record=resume_job(job_id,{'approved':action=='approve','fingerprint':payload['fingerprint'],'actor':'local_dashboard'},None,store)
        return pipeline(job_id,agents,store) if record['status']=='APPROVED' else record
    if action=='continue':return pipeline(job_id,agents,store)
    if action=='security':
        record=security_job(job_id,agents,store)
        return write_report(job_id,agents,store) if record['status']=='SECURITY_PASSED' else record
    if action=='preview_start':
        record=start_preview(job_id,store,approved=payload.get('approved') is True,actor='local_dashboard')
        if record['status']=='PREVIEW_RUNNING':record=write_report(job_id,agents,store)
        return record
    if action=='preview_stop':return stop_preview(job_id,store)
    if action=='preview_status':return preview_status(job_id,store)
    if action=='report':return write_report(job_id,agents,store)
    raise ValueError('Unknown dashboard action')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('payload',type=Path)
    args=parser.parse_args();data=json.loads(args.payload.read_text(encoding='utf-8'))
    store=JobStore(Path(data['db']))
    try:
        agents=OllamaAgents(job_model(store.read(data['job_id'])))
        agents.trace_directory=args.payload.parent/'model-calls'
        record=execute(data['job_id'],data['action'],data['payload'],store,agents)
    except ValueError as exc:
        store.event(data['job_id'],'ACTION_REJECTED',{'reason':str(exc)[:1500]},update_status=False)
        print(json.dumps({'job_id':data['job_id'],'error':str(exc)[:1500]}))
        return 1
    print(json.dumps({'job_id':record['job_id'],'status':record['status']}))
    browser_failed=data['action']=='browser_check' and next((e['status'] for e in reversed(record['events']) if e['status'] in {'AUTOMATED_BROWSER_PASSED','AUTOMATED_BROWSER_FAILED'}),None)!='AUTOMATED_BROWSER_PASSED'
    return int(browser_failed or record['status'] in {'FAILED','VERIFICATION_FAILED','SECURITY_BLOCKED','PREVIEW_FAILED'})


if __name__=='__main__':raise SystemExit(main())
