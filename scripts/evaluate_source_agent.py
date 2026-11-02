"""Generate a disposable source fixture from a saved agent design and run real build checks.

No normal app approval, behavior coverage, preview or deployment is claimed.
"""
import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

from forge.agents import OllamaAgents
from forge.autonomous_planning import AppDraft
from forge.coordinator import TaskCoordinator
from forge.persistence import JobStore
from forge.senior_review import SeniorReviewer
from forge.source_agent import SourceAgent,build_evidence
from forge.tasks import CheckEvidence,Dependency,Observation,Task,TaskLedger
from forge.workspace import safe_path,seed_workspace,source_fingerprint
from forge.workspace_tools import WorkspaceTools,file_hash


PROJECT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case-directory',type=Path,required=True)
    args=parser.parse_args()
    saved=json.loads((args.case_directory/'job.json').read_text(encoding='utf-8'))
    review=next(e['payload'] for e in reversed(saved['events']) if e['status']=='AUTONOMOUS_DRAFT_READY')
    path=Path(review['report'])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=review['draft_sha256']:raise ValueError('Saved proposal fingerprint differs')
    draft=AppDraft.model_validate_json(path.read_text(encoding='utf-8'))
    if any(file.owner=='qa' for file in draft.files):raise ValueError('This source/build fixture does not execute QA-authored test files; independent behavior testing is a separate increment')
    original=saved['events'][0]['payload']['description']
    directory=PROJECT/'artifacts/source-agent-evaluation'/uuid4().hex
    store=JobStore(directory/'jobs.sqlite3');job=store.create({'description':'Internal source-agent fixture; not a human-approved app run'})
    ledger=TaskLedger(store,job);boundary=PROJECT/'workspace/.tool-fixtures';root=boundary/job
    parent=ledger.start(ledger.create(Task(owner='coordinator',goal='Verify model source writes and isolated build checks on a disposable fixture',required_checks=['source_fixture'])))
    agent=OllamaAgents('qwen2.5-coder:7b');agent.trace_directory=directory/'model-calls'
    summary={'job_id':job,'passed':False,'source_generation':'NOT_RUN','build':'NOT_RUN',
        'application_behavior':'NOT_TESTED','preview':'NOT_STARTED','deployment':'NOT_RUN','cleanup_errors':[]}
    print('Evidence: '+str(directory),flush=True)
    try:
        seed_workspace(PROJECT/'templates/task-app',root,generic=True)
        writer=SourceAgent(ledger,agent,root,draft,workspace_boundary=boundary)
        predecessors=[]
        for file in draft.files:
            state=ledger.create(Task(parent_id=parent.task.id,owner=file.owner,
                goal=f'Deliver the complete proposed source for {file.path}: {file.purpose}',
                inputs={'original_request':original,'file':file.path},
                dependencies=[Dependency(task_id=t.task.id,revision=t.revision) for t in predecessors],
                required_checks=['source_written']),action_limit=6)
            reviewer=SeniorReviewer(agent,ledger,{file.owner},capabilities={file.owner:'Owns the assigned source file and its implementation within the supplied app design.'})
            target=safe_path(root,file.path)
            state=TaskCoordinator(ledger,{file.owner:writer},reviewer,
                lambda:file_hash(target) or hashlib.sha256(b'').hexdigest()).run(state.task.id)
            print(json.dumps({'file':file.path,'status':state.status,'dispatches':state.actions_used}),flush=True)
            if state.status!='completed':raise RuntimeError('Source task paused: '+state.pause_reason)
            predecessors.append(state)
        summary['source_generation']='COMPLETED_UNVERIFIED'
        owners={file.owner for file in draft.files}
        if len(owners)!=1:raise ValueError('This initial source/build fixture expects one source owner; cross-owner repair delegation is not silently bypassed')
        owner=next(iter(owners))
        build=ledger.create(Task(parent_id=parent.task.id,owner=owner,
            goal='Make the generated candidate pass actual isolated build checks without weakening requested behavior.',
            inputs={'original_request':original,'mode':'repair_build'},
            dependencies=[Dependency(task_id=t.task.id,revision=t.revision) for t in predecessors],
            required_checks=['isolated_build']),action_limit=8)
        def verify_or_repair(state):
            if not state.observations:return build_evidence(WorkspaceTools(ledger,state,root,draft,workspace_boundary=boundary))
            return writer(state)
        reviewer=SeniorReviewer(agent,ledger,{owner},context_loader=lambda state:{
            'original_request':original,'app_design':draft.model_dump(),
            'current_source':{file.path:safe_path(root,file.path).read_text(encoding='utf-8') for file in draft.files}},
            capabilities={owner:'Owns the current source files; can repair them using actual compiler/build evidence.'})
        build=TaskCoordinator(ledger,{owner:verify_or_repair},reviewer,lambda:source_fingerprint(root)).run(build.task.id)
        summary['build']='PASSED' if build.status=='completed' else 'PAUSED'
        summary['build_dispatches']=build.actions_used;summary['build_task_id']=build.task.id
        if build.status!='completed':raise RuntimeError('Build task paused: '+build.pause_reason)
        summary['passed']=True;summary['final_source_fingerprint']=source_fingerprint(root)
        ledger.observe(parent,Observation(revision=parent.revision,fingerprint=summary['final_source_fingerprint'],
            checks=[CheckEvidence(check='source_fixture',exit_code=0,fingerprint=summary['final_source_fingerprint'],
                report=str((directory/'result.json').resolve()),summary='Model source saved and actual build checks passed. Application behavior remains untested.')]))
    except Exception as exc:summary['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if root.exists():
            target=root.resolve()
            if target.parent!=boundary.resolve() or not re.fullmatch(r'[a-f0-9]{32}',target.name):
                summary['cleanup_errors'].append('Fixture cleanup boundary check failed')
            else:
                try:
                    shutil.copytree(target,directory/'source')
                    summary['archived_source_fingerprint']=source_fingerprint(directory/'source')
                    shutil.rmtree(target)
                except Exception as exc:summary['cleanup_errors'].append(str(exc))
        summary['model_calls']=len(list((directory/'model-calls').glob('*.json')))
        summary['senior_reviews']=sum(e['status']=='TASK_RECOVERY_PLANNED' for e in store.read(job)['events'])
        (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        (directory/'job.json').write_text(json.dumps(store.read(job),indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)
    return int(not summary['passed'] or bool(summary['cleanup_errors']))


if __name__=='__main__':raise SystemExit(main())
