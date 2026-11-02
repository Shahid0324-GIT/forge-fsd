"""Resume a paused disposable source-agent evaluation without regenerating its files."""
import argparse
import json
import re
import shutil
from pathlib import Path

from forge.agents import OllamaAgents
from forge.autonomous_planning import AppDraft
from forge.coordinator import TaskCoordinator
from forge.handoffs import read_handoff
from forge.persistence import JobStore
from forge.senior_review import SeniorReviewer
from forge.source_agent import SourceAgent
from forge.tasks import CheckEvidence,Observation,TaskLedger
from forge.workspace import safe_path,source_fingerprint


PROJECT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--additional-actions',type=int,default=8)
    args=parser.parse_args();directory=args.directory.resolve()
    if not directory.is_relative_to((PROJECT/'artifacts/source-agent-evaluation').resolve()):raise ValueError('Evaluation directory outside artifact boundary')
    latest=directory/'resume-latest.json'
    original=json.loads((latest if latest.exists() else directory/'result.json').read_text(encoding='utf-8'))
    job=original['job_id']
    if not re.fullmatch(r'[a-f0-9]{32}',job):raise ValueError('Invalid fixture identity')
    store=JobStore(directory/'jobs.sqlite3');ledger=TaskLedger(store,job)
    build=ledger.read(original['build_task_id'])
    if build.status!='paused':raise ValueError('Only a paused saved build task can resume')
    snapshot=Path(original.get('source_archive',str(directory/'source'))).resolve()
    if not snapshot.is_relative_to(directory):raise ValueError('Source archive outside evaluation directory')
    if source_fingerprint(snapshot)!=original['archived_source_fingerprint']:raise ValueError('Archived source differs from the saved checkpoint')
    data=None
    for event in store.read(job)['events']:
        if event['status']=='AGENT_HANDOFF':
            packet=read_handoff(Path(event['payload']['report']),event['payload'])
            if 'app_design' in packet['context']:data=packet['context'];break
    if data is None:raise ValueError('Original app design/context is missing')
    draft=AppDraft.model_validate(data['app_design']);request=data['original_request']
    boundary=PROJECT/'workspace/.tool-fixtures';root=boundary/job
    if root.exists():raise ValueError('Fixture workspace already exists; reconcile it before restoring')
    if root.resolve().parent!=boundary.resolve():raise ValueError('Fixture restore boundary failed')
    shutil.copytree(snapshot,root)
    build=ledger.resume(build,additional_actions=args.additional_actions)
    agent=OllamaAgents('qwen2.5-coder:7b');agent.trace_directory=directory/'model-calls'
    before_calls=len(list(agent.trace_directory.glob('*.json')))
    writer=SourceAgent(ledger,agent,root,draft,workspace_boundary=boundary)
    reviewer=SeniorReviewer(agent,ledger,{build.task.owner},context_loader=lambda state:{
        'original_request':request,'app_design':draft.model_dump(),
        'current_source':{file.path:safe_path(root,file.path).read_text(encoding='utf-8') for file in draft.files}},
        capabilities={build.task.owner:'Owns these source files and may correct them using actual build evidence; requirements and tests cannot be weakened.'})
    summary={**original,'passed':False,'build':'PAUSED','cleanup_errors':[],'resumed_from_actions':build.actions_used}
    summary.pop('error',None)
    label='resume-'+str(build.action_limit)
    result_path=directory/(label+'.json')
    try:
        build=TaskCoordinator(ledger,{build.task.owner:writer},reviewer,lambda:source_fingerprint(root)).run(build.task.id)
        summary.update(build='PASSED' if build.status=='completed' else 'PAUSED',build_dispatches=build.actions_used,
                       passed=build.status=='completed',pause_reason=build.pause_reason)
        if summary['passed']:
            parent=ledger.read(build.task.parent_id)
            fingerprint=source_fingerprint(root)
            ledger.observe(parent,Observation(revision=parent.revision,fingerprint=fingerprint,
                checks=[CheckEvidence(check='source_fixture',exit_code=0,fingerprint=fingerprint,report=str(result_path),
                    summary='Resumed model edits passed actual typecheck/build; application behavior is still NOT_TESTED.')]))
    except Exception as exc:summary['error']=f'{type(exc).__name__}: {exc}'
    finally:
        target=root.resolve();archive=directory/('source-'+label)
        if target.parent!=boundary.resolve() or not re.fullmatch(r'[a-f0-9]{32}',target.name):
            summary['cleanup_errors'].append('Fixture cleanup boundary failed')
        else:
            try:
                shutil.copytree(target,archive)
                summary['source_archive']=str(archive)
                summary['archived_source_fingerprint']=source_fingerprint(archive)
                shutil.rmtree(target)
            except Exception as exc:summary['cleanup_errors'].append(str(exc))
        summary['model_calls']=len(list(agent.trace_directory.glob('*.json')))
        summary['new_model_calls']=summary['model_calls']-before_calls
        summary['senior_reviews']=sum(e['status']=='TASK_RECOVERY_PLANNED' for e in store.read(job)['events'])
        result_path.write_text(json.dumps(summary,indent=2),encoding='utf-8')
        latest.write_text(json.dumps(summary,indent=2),encoding='utf-8')
        (directory/(label+'-job.json')).write_text(json.dumps(store.read(job),indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)
    return int(not summary['passed'] or bool(summary['cleanup_errors']))


if __name__=='__main__':raise SystemExit(main())
