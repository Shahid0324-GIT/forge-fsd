import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from forge.autonomous_planning import AppDraft
from forge.persistence import JobStore
from forge.tasks import Task,TaskConflict,TaskLedger
from forge.workspace import seed_workspace
from forge.workspace import source_fingerprint
from forge.workspace_tools import ToolCall,WorkspaceTools,file_hash


PROJECT=Path(__file__).resolve().parents[1]


@pytest.fixture
def tools(tmp_path):
    store=JobStore(tmp_path/'artifacts/jobs.sqlite3');job=store.create()
    ledger=TaskLedger(store,job)
    state=ledger.reserve_action(ledger.start(ledger.create(Task(owner='frontend',goal='Implement a page',required_checks=['file_saved']))),'frontend')
    root=tmp_path/'workspace'/job;seed_workspace(PROJECT/'templates/task-app',root,generic=True)
    draft=AppDraft(title='A page',design='App-owned structure',database='none',acceptance_criteria=['Display a page'],test_strategy='Build and browser checks',
        files=[{'path':'app/page.tsx','owner':'frontend','purpose':'Home page'},
               {'path':'lib/types.ts','owner':'backend','purpose':'Shared types'},
               {'path':'app/tests/page.test.ts','owner':'qa','purpose':'Independent behavior checks'}])
    return WorkspaceTools(ledger,state,root,draft,workspace_boundary=tmp_path/'workspace')


def test_tools_expose_actual_dependencies_and_only_implemented_checks(tools):
    available=tools.describe()
    assert available['declared_app_dependencies']['react']
    assert 'jest' not in available['declared_dev_dependencies']
    assert available['checks_available']==['typecheck','production_build']
    assert 'browser_interactions' in available['coverage_not_yet_provided']
    assert not available['host_shell'] and not available['package_installation']


def test_read_write_and_trace_preserve_source_and_real_task_identity(tools):
    read=tools.execute({'tool':'read_file','path':'app/page.tsx'})
    assert read['data']['exists'] is False
    content='export default function Page(){return <main>Fixture</main>}\n'
    written=tools.execute({'tool':'write_file','path':'app/page.tsx','content':content,'expected_sha256':None})
    assert written['ok'] and (tools.root/'app/page.tsx').read_text()==content
    assert written['before_content'] is None and written['source_before']!=written['source_after']
    saved=tools.execute({'tool':'read_file','path':'app/page.tsx'})
    replaced=tools.execute({'tool':'write_file','path':'app/page.tsx','content':'export default function Page(){return null}','expected_sha256':saved['data']['sha256']})
    assert replaced['ok'] and replaced['before_content']==content
    assert json.loads(Path(replaced['report']).read_text())['task_id']==tools.state.task.id
    assert tools.ledger.read(tools.state.task.id).status=='running'  # Writes do not prove task/application success.
    assert tools.ledger.store.read(tools.ledger.job_id)['status']=='RECEIVED'


def test_stale_file_hash_cannot_overwrite_new_source(tools):
    path=tools.root/'app/page.tsx';path.write_text('new source',encoding='utf-8')
    outcome=tools.execute({'tool':'write_file','path':'app/page.tsx','content':'stale edit','expected_sha256':None})
    assert not outcome['ok'] and 'changed since' in outcome['error']
    assert path.read_text()=='new source'


def test_repair_cannot_repeat_unchanged_source_as_a_correction(tools):
    path=tools.root/'app/page.tsx';path.write_text('export default function Page(){return null}',encoding='utf-8')
    outcome=tools.execute({'tool':'write_file','path':'app/page.tsx','content':path.read_text(),
        'expected_sha256':file_hash(path),'require_change':True})
    assert not outcome['ok'] and 'unchanged source' in outcome['error']
    assert outcome['source_before']==outcome['source_after']


def test_exact_text_patch_preserves_unrelated_source_and_before_image(tools):
    path=tools.root/'app/page.tsx';before='export default function Page(){return null}\n'
    path.write_text(before,encoding='utf-8')
    result=tools.execute({'tool':'replace_text','path':'app/page.tsx',
        'edits':[{'old':'return null','new':'return <main>Fixed</main>'}],
        'expected_sha256':file_hash(path),'expected_workspace_fingerprint':source_fingerprint(tools.root)})
    assert result['ok'] and result['before_content']==before
    assert path.read_text()=='export default function Page(){return <main>Fixed</main>}\n'


@pytest.mark.parametrize('edits',[[{'old':'missing','new':'new'}],[{'old':'return','new':'return'}],
    [{'old':'return null','new':'return 1'},{'old':'missing','new':'new'}]])
def test_bad_or_noop_patch_is_rejected_without_partial_mutation(tools,edits):
    path=tools.root/'app/page.tsx';before='export default function Page(){return null}'
    path.write_text(before,encoding='utf-8')
    result=tools.execute({'tool':'replace_text','path':'app/page.tsx','edits':edits,
        'expected_sha256':file_hash(path),'expected_workspace_fingerprint':source_fingerprint(tools.root)})
    assert not result['ok'] and path.read_text()==before


@pytest.mark.parametrize('noop_first',[True,False])
def test_mixed_patch_rejects_unchanged_edit_and_records_actionable_feedback(tools,noop_first):
    path=tools.root/'app/page.tsx';before='export default function Page(){return null}'
    path.write_text(before,encoding='utf-8')
    noop={'old':'export default','new':'export default'}
    change={'old':'return null','new':'return <main>Changed</main>'}
    result=tools.execute({'tool':'replace_text','path':'app/page.tsx',
        'edits':[noop,change] if noop_first else [change,noop],
        'expected_sha256':file_hash(path),'expected_workspace_fingerprint':source_fingerprint(tools.root)})
    assert not result['ok'] and path.read_text()==before
    assert f'Patch edit {1 if noop_first else 2} is unchanged' in result['error']
    assert 'omit this edit' in result['error']
    assert result['source_before']==result['source_after']
    saved=json.loads(Path(result['report']).read_text())
    assert saved['error']==result['error'] and saved['phase']=='failed'


@pytest.mark.parametrize('path',['../control-plane.py','package.json','lib/types.ts','app/tests/page.test.ts','app/new-helper.ts'])
def test_writes_cannot_escape_scope_change_dependencies_or_edit_other_owners(tools,path):
    outcome=tools.execute({'tool':'write_file','path':path,'content':'overwrite','expected_sha256':None})
    assert not outcome['ok']


def test_stale_dispatch_cannot_read_or_mutate_workspace(tools):
    tools.ledger.revise(tools.state,tools.state.task.model_copy(update={'inputs':{'contract':'revised'}}))
    with pytest.raises(TaskConflict,match='stale or inactive'):
        tools.execute({'tool':'write_file','path':'app/page.tsx','content':'old work','expected_sha256':None})
    assert not (tools.root/'app/page.tsx').exists()


def test_invalid_tool_and_model_supplied_roles_are_not_executable():
    with pytest.raises(ValidationError):ToolCall.model_validate({'tool':'run_shell','command':'anything'})
    with pytest.raises(ValidationError):ToolCall.model_validate({'tool':'list_files','owner':'qa'})


def test_unsupported_packages_are_rejected_without_rewriting_the_agent_source(tools):
    content='import {Button} from "some-uninstalled-library"; export default function Page(){return <Button/>}'
    outcome=tools.execute({'tool':'write_file','path':'app/page.tsx','content':content,'expected_sha256':None})
    assert not outcome['ok'] and 'some-uninstalled-library' in outcome['error']
    assert not (tools.root/'app/page.tsx').exists()


def test_pure_shared_client_helpers_are_not_mistaken_for_database_imports(tools):
    content='"use client"; import {calculate} from "@/lib/math"; export default function Page(){return <main>{calculate(2)}</main>}'
    outcome=tools.execute({'tool':'write_file','path':'app/page.tsx','content':content,'expected_sha256':None})
    assert outcome['ok'] and (tools.root/'app/page.tsx').read_text()==content


def test_protected_runtime_changes_invalidate_the_tool_session(tools):
    (tools.root/'package.json').write_text('{}',encoding='utf-8')
    with pytest.raises(TaskConflict,match='runtime configuration changed'):tools.describe()


def test_build_tool_success_is_not_confused_with_passing_checks(tools):
    def failed(root,directory,job):
        return {'passed':False,'report':'build.json','coverage':{'typecheck':'FAILED','application_behavior':'NOT_TESTED'},
            'source_fingerprint':'a'*64,'checks':{'results':[{'name':'typecheck','exit_code':1,'output':'Real compiler failure','stopped':None}]}}
    tools.check_runner=failed
    outcome=tools.execute({'tool':'check_build'})
    assert outcome['ok'] and outcome['data']['passed'] is False
    assert outcome['data']['checks'][0]['output']=='Real compiler failure'


def test_nested_test_files_require_qa_ownership(tools):
    proposed=tools.draft.model_copy(deep=True)
    proposed.files[-1].owner='frontend'
    with pytest.raises(ValueError,match='belong to QA'):
        WorkspaceTools(tools.ledger,tools.state,tools.root,proposed,workspace_boundary=tools.root.parent)
