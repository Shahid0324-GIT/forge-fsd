"""Resume an archived internal app-QA resource pause without changing its assertions."""
import argparse
import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

from forge.agents import OllamaAgents
from forge.autonomous_testing import test_app
from forge.models import job_model
from forge.persistence import JobStore
from forge.source_checks import PROJECT
from forge.workspace import source_fingerprint


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evaluation',type=Path)
    parser.add_argument('--actions',type=int,default=8)
    args=parser.parse_args();base=args.evaluation.resolve()
    if not base.is_relative_to((PROJECT/'artifacts/approved-build-evaluation').resolve()) or not (base/'jobs.sqlite3').is_file():
        parser.error('Select an existing internal approved-build evaluation directory')
    if not 1<=args.actions<=16:parser.error('Use 1–16 additional dispatches')
    saved=json.loads((base/'result.json').read_text(encoding='utf-8'));job=saved['job_id']
    if not re.fullmatch(r'[a-f0-9]{32}',job):parser.error('Invalid evaluation job identity')
    store=JobStore(base/'jobs.sqlite3');record=store.read(job)
    if record['status']!='AUTONOMOUS_TEST_PAUSED':parser.error('Only a saved app-QA resource pause can resume here')
    boundary=PROJECT/'workspace/.approved-fixtures';root=(boundary/job).resolve()
    if not root.is_relative_to((PROJECT/'workspace').resolve()) or root.parent!=boundary.resolve() or root.exists():
        parser.error('Disposable workspace must be absent and within the evaluation boundary')
    pointer=base/'resume-pointer.json'
    checkpoint=json.loads(pointer.read_text()) if pointer.exists() else {'source':str(base/'source'),'source_fingerprint':saved['source_fingerprint']}
    archive=Path(checkpoint['source']).resolve()
    if not archive.is_relative_to(base) or source_fingerprint(archive)!=checkpoint['source_fingerprint']:parser.error('Archived source fingerprint changed')
    directory=base/('resume-'+uuid4().hex);directory.mkdir()
    summary={'job_id':job,'passed':False,'human_approval':'NOT_CLAIMED','cleanup_errors':[],
        'scope':'Resume of an internal model-generated app evaluation; frozen assertions retained.'}
    before=next(e['payload']['contract_fingerprint'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_ACCEPTANCE_FROZEN')
    agents=OllamaAgents(job_model(record));agents.trace_directory=directory/'model-calls'
    print('Evidence: '+str(directory),flush=True)
    try:
        shutil.copytree(archive,root)
        record=test_app(job,agents,store,resume=True,additional_actions=args.actions,workspace_boundary=boundary)
        summary.update(status=record['status'],passed=record['status']=='AUTONOMOUS_APP_CHECKS_PASSED')
        after=next(e['payload']['contract_fingerprint'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_ACCEPTANCE_FROZEN')
        summary['frozen_contract_unchanged']=before==after
        if summary['passed']:summary['final_report']=record['events'][-1]['payload']['report']
    except Exception as exc:summary['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if root.exists():
            if root.parent!=boundary.resolve():raise ValueError('Cleanup boundary changed')
            try:
                shutil.copytree(root,directory/'source');summary['source_fingerprint']=source_fingerprint(directory/'source');shutil.rmtree(root)
            except Exception as exc:summary['cleanup_errors'].append(str(exc))
        summary['model_calls']=len(list((directory/'model-calls').glob('*.json')))
        summary['passed']=bool(summary['passed'] and summary.get('frozen_contract_unchanged') and not summary['cleanup_errors'])
        (directory/'job.json').write_text(json.dumps(store.read(job),indent=2),encoding='utf-8')
        (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        if 'source_fingerprint' in summary and not summary['cleanup_errors']:
            pointer.write_text(json.dumps({'source':str(directory/'source'),'source_fingerprint':summary['source_fingerprint']},indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True)
    return int(not summary['passed'])


if __name__=='__main__':raise SystemExit(main())
