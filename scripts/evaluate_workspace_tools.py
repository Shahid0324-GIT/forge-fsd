"""Exercise real scoped edits and Docker checks on a disposable static fixture.

This is tool verification, not an autonomous generated-app success claim.
"""
import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

from forge.autonomous_planning import AppDraft
from forge.persistence import JobStore
from forge.tasks import CheckEvidence,Observation,Task,TaskLedger
from forge.workspace import seed_workspace,source_fingerprint
from forge.workspace_tools import WorkspaceTools


PROJECT=Path(__file__).resolve().parents[1]


def main():
    directory=PROJECT/'artifacts/tool-evaluation'/uuid4().hex
    store=JobStore(directory/'jobs.sqlite3');job=store.create({'description':'Disposable static tool verification fixture; not an agent-built app'})
    boundary=PROJECT/'workspace/.tool-fixtures';root=boundary/job
    ledger=TaskLedger(store,job)
    task=ledger.reserve_action(ledger.start(ledger.create(Task(owner='builder',
        goal='Verify scoped editing and isolated build tools on a static fixture',required_checks=['tool_fixture']))),'builder')
    draft=AppDraft(title='Tool fixture',design='Static fixture; no user app execution claim.',database='none',
        files=[{'path':'app/page.tsx','owner':'builder','purpose':'Build-tool fixture'}],
        acceptance_criteria=['Compiler errors are observed and a corrected fixture builds'],test_strategy='Typecheck and production build only')
    summary={'job_id':job,'scope':'Static tool fixture; no model calls, app behavior tests, preview or deployment.',
        'passed':False,'cleanup_errors':[]}
    try:
        seed_workspace(PROJECT/'templates/task-app',root,generic=True)
        tools=WorkspaceTools(ledger,task,root,draft,workspace_boundary=boundary)
        bad='export default function Page(){const value: number="wrong";return <main>{value}</main>}\n'
        write=tools.execute({'tool':'write_file','path':'app/page.tsx','content':bad,'expected_sha256':None})
        if not write['ok']:raise RuntimeError(write['error'])
        failure=tools.execute({'tool':'check_build'})
        summary['failing_build']=failure
        if not failure['ok'] or failure['data']['passed'] is not False:raise RuntimeError('The intentionally invalid fixture was not rejected as expected')
        if not any(row['name']=='typecheck' and row['exit_code'] not in {None,0} for row in failure['data']['checks']):
            raise RuntimeError('No actual compiler failure was observed; inspect the environment/tool report')
        current=tools.execute({'tool':'read_file','path':'app/page.tsx'})
        good='export default function Page(){return <main><h1>Tool verification fixture</h1></main>}\n'
        edit=tools.execute({'tool':'write_file','path':'app/page.tsx','content':good,'expected_sha256':current['data']['sha256']})
        if not edit['ok']:raise RuntimeError(edit['error'])
        success=tools.execute({'tool':'check_build'});summary['corrected_build']=success
        if not success['ok'] or success['data']['passed'] is not True:raise RuntimeError('Corrected static fixture did not pass isolated build checks')
        summary['passed']=True;summary['final_source_fingerprint']=source_fingerprint(root)
        ledger.observe(task,Observation(revision=task.revision,fingerprint=summary['final_source_fingerprint'],
            checks=[CheckEvidence(check='tool_fixture',exit_code=0,fingerprint=summary['final_source_fingerprint'],
                report=str((directory/'result.json').resolve()),summary='Known failing and corrected static fixtures produced expected tool results; no app behavior was tested.')]))
    except Exception as exc:summary['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if root.exists():
            # Only this invocation's disposable child is eligible for recursive cleanup.
            target=root.resolve();parent=boundary.resolve()
            if target.parent!=parent or not re.fullmatch(r'[a-f0-9]{32}',target.name):
                summary['cleanup_errors'].append('Fixture cleanup boundary check failed')
            else:
                try:shutil.rmtree(target)
                except Exception as exc:summary['cleanup_errors'].append(str(exc))
        (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        (directory/'job.json').write_text(json.dumps(store.read(job),indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(directory),'passed':summary['passed'],'error':summary.get('error'),
        'cleanup_errors':summary['cleanup_errors'],'scope':summary['scope']}),flush=True)
    return int(not summary['passed'] or bool(summary['cleanup_errors']))


if __name__=='__main__':raise SystemExit(main())
