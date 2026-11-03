"""Fixed internal evaluation: local-model planning -> test-actor approval -> generated source/build.

This is not a human approval or a user app release. The fixed counter request, isolated
workspace and explicit evaluation actor keep this separate from normal dashboard jobs.
"""
import json
import argparse
import re
import shutil
from pathlib import Path
from uuid import uuid4

from forge.agents import OllamaAgents
from forge.autonomous_build import build_app
from forge.autonomous_planning import plan_app
from forge.autonomous_review import decide_plan,review_snapshot,request_changes
from forge.autonomous_testing import test_app
from forge.persistence import JobStore
from forge.source_checks import PROJECT
from forge.workspace import source_fingerprint


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-checks',action='store_true',help='Run independent requirements-derived browser checks after generation/build.')
    parser.add_argument('--review-feedback',help='Internal operator feedback through the normal request-changes flow before approval.')
    args=parser.parse_args()
    directory=PROJECT/'artifacts/approved-build-evaluation'/uuid4().hex;directory.mkdir(parents=True)
    store=JobStore(directory/'jobs.sqlite3');agents=OllamaAgents('qwen2.5-coder:7b')
    agents.trace_directory=directory/'model-calls';boundary=PROJECT/'workspace/.approved-fixtures'
    summary={'passed':False,'approval_actor':'internal_evaluation','human_approval':'NOT_CLAIMED',
        'application_behavior':'NOT_TESTED','preview':'NOT_STARTED','deployment':'NOT_RUN','cleanup_errors':[]}
    root=None;job=None
    print('Evidence: '+str(directory),flush=True)
    try:
        record=plan_app('Build a single-page counter with an Increment button. Start at zero and add one per click. No saved data.',agents,store)
        job=record['job_id'];root=boundary/job;summary['job_id']=job
        if record['status']!='AUTONOMOUS_DRAFT_READY':raise RuntimeError('Internal planning did not reach a reviewable proposal')
        review=review_snapshot(job,store)
        if args.review_feedback:
            (directory/'initial-review.json').write_text(json.dumps(review,indent=2),encoding='utf-8')
            record=request_changes(job,agents,store,review['fingerprint'],args.review_feedback,actor='internal_evaluation')
            if record['status']!='AUTONOMOUS_DRAFT_READY':raise RuntimeError('Feedback did not reach a reviewable proposal')
            review=review_snapshot(job,store)
        if review['draft']['database']!='none':raise ValueError('The fixed stateless evaluation unexpectedly proposed a database')
        (directory/'review.json').write_text(json.dumps(review,indent=2),encoding='utf-8')
        decide_plan(job,store,review['fingerprint'],approved=True,actor='internal_evaluation')
        record=build_app(job,agents,store,workspace_boundary=boundary)
        if args.app_checks and record['status']=='AUTONOMOUS_BUILD_CHECKS_PASSED':
            record=test_app(job,agents,store,workspace_boundary=boundary)
        expected='AUTONOMOUS_APP_CHECKS_PASSED' if args.app_checks else 'AUTONOMOUS_BUILD_CHECKS_PASSED'
        summary.update(status=record['status'],passed=record['status']==expected)
        if args.app_checks:summary['application_behavior']='SELECTED_REQUIREMENTS_BROWSER_CHECKS' if summary['passed'] else 'NOT_VERIFIED'
        if summary['passed']:summary['final_report']=record['events'][-1]['payload']['report']
    except Exception as exc:summary['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if root is not None and root.exists():
            target=root.resolve()
            if target.parent!=boundary.resolve() or not re.fullmatch(r'[a-f0-9]{32}',target.name):
                summary['cleanup_errors'].append('Fixture cleanup boundary failed')
            else:
                try:
                    shutil.copytree(target,directory/'source');summary['source_fingerprint']=source_fingerprint(directory/'source')
                    shutil.rmtree(target)
                except Exception as exc:summary['cleanup_errors'].append(str(exc))
        summary['model_calls']=len(list((directory/'model-calls').glob('*.json')))
        summary['passed']=bool(summary['passed'] and not summary['cleanup_errors'])
        if job:(directory/'job.json').write_text(json.dumps(store.read(job),indent=2),encoding='utf-8')
        (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)
    return int(not summary['passed'])


if __name__=='__main__':raise SystemExit(main())
