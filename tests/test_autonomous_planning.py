import json

import pytest

from forge.autonomous_planning import AppDraft,answer_intake,continue_draft,manifest_issues,plan_app,start_planning
from forge.persistence import JobStore
from forge.contracts import IntakeDecision
from forge.tasks import TaskLedger


def draft(**changes):
    return AppDraft(title='A small app',design='Choose app-owned interfaces and state; no platform business types.',
        database='none',files=[{'path':'app/page.tsx','owner':'builder','purpose':'The complete interactive page'}],
        acceptance_criteria=['Display the requested behavior'],test_strategy='Build and browser interaction checks',**changes)


class Agent:
    model_name='qwen2.5-coder:7b'
    def __init__(self,proposal,blocked=False):self.proposal=proposal;self.calls=[];self.blocked=blocked
    def generate(self,schema,instruction,data,**_):
        self.calls.append((schema,data))
        if schema is AppDraft:return self.proposal
        assert schema is IntakeDecision
        return schema.model_validate({'intent':'clarify','blocking_reason':'Requested service is not supported',
            'questions':['Can the requested payments integration be omitted?']} if self.blocked else {'intent':'build'})


def test_client_only_plan_does_not_need_routes_entities_or_backend_task(tmp_path):
    agent=Agent(draft());store=JobStore(tmp_path/'jobs.sqlite3')
    result=plan_app('Build a small interactive page.',agent,store)
    assert result['status']=='AUTONOMOUS_DRAFT_READY'
    report=result['events'][-1]['payload']
    assert report['app_execution']=='NOT_RUN' and report['approval']=='NOT_APPROVED'
    proposed=json.loads(__import__('pathlib').Path(report['report']).read_text())
    assert proposed['database']=='none' and len(proposed['files'])==1
    assert 'routes' not in proposed and 'entities' not in proposed
    assert [item['owner'] for item in proposed['files']]==['builder']


@pytest.mark.parametrize('path',['../escape.tsx','/outside.tsx','app/../../outside.ts','package.json','app/.env.ts','app/node_modules/bad.ts'])
def test_manifest_checks_workspace_boundaries_without_prescribing_business_design(tmp_path,path):
    proposal=draft();proposal.files[0].path=path
    assert manifest_issues(proposal,tmp_path/'unexecuted')


def test_duplicate_ownership_and_builder_owned_tests_are_rejected(tmp_path):
    proposal=draft()
    proposal.files.append(proposal.files[0].model_copy(update={'owner':'frontend'}))
    proposal.files.append(proposal.files[0].model_copy(update={'path':'tests/behavior.ts'}))
    issues=manifest_issues(proposal,tmp_path/'unexecuted')
    assert any('conflicting ownership' in error for error in issues)
    assert any('belong to QA' in error for error in issues)


def test_agent_can_define_product_types_without_reserved_platform_type_conflicts(tmp_path):
    proposal=draft();proposal.database='sqlite'
    proposal.design='Define an app-owned Product type, a stock movement type and shared API interfaces. Choose suitable fields and relationships.'
    assert manifest_issues(proposal,tmp_path/'unexecuted')==[]


def test_paused_draft_resumes_with_actual_failure_context_and_new_strategy(tmp_path):
    bad=draft();bad.files[0].path='package.json'
    agent=Agent(bad);store=JobStore(tmp_path/'jobs.sqlite3')
    paused=plan_app('Build a small interactive page.',agent,store,action_limit=1)
    assert paused['status']=='AUTONOMOUS_PAUSED'
    ledger=TaskLedger(store,paused['job_id']);task=next(t for t in ledger.list() if t.task.owner=='planner')
    ledger.resume(task,additional_actions=1)
    agent.proposal=draft()
    result=continue_draft(ledger,task.task.id,agent)
    assert result['status']=='AUTONOMOUS_DRAFT_READY'
    assert len(agent.calls)==3
    assert agent.calls[-1][1]['latest_proposal']['files'][0]['path']=='package.json'
    assert agent.calls[-1][1]['recent_failures'][-1]['checks'][1]['exit_code']==1
    assert ledger.read(task.task.id).actions_used==2


def test_genuine_questions_do_not_enable_app_generation(tmp_path):
    agent=Agent(draft(),blocked=True)
    result=plan_app('Build a page with a payment integration.',agent,JobStore(tmp_path/'jobs.sqlite3'))
    assert result['status']=='AUTONOMOUS_INPUT_NEEDED'
    assert result['events'][-1]['payload']['approval']=='NOT_APPROVED'


def test_requirements_delegate_understood_goal_to_a_planner_with_exact_context(tmp_path):
    agent=Agent(draft())
    store=JobStore(tmp_path/'jobs.sqlite3');result=plan_app('Build a small calculator with no stored data.',agent,store)
    assert result['status']=='AUTONOMOUS_DRAFT_READY' and len(agent.calls)==2
    states=TaskLedger(store,result['job_id']).list()
    intake=next(t for t in states if t.task.owner=='requirements');child=next(t for t in states if t.task.owner=='planner')
    assert child.status=='completed' and child.task.parent_id==intake.task.id
    assert child.task.dependencies[0].revision==intake.revision
    assert agent.calls[-1][1]['original_request']=='Build a small calculator with no stored data.'


def test_clarification_revises_same_run_and_preserves_original_requirements(tmp_path):
    agent=Agent(draft(),blocked=True);store=JobStore(tmp_path/'jobs.sqlite3')
    initial=plan_app('Build a landing page with payment integration.',agent,store)
    agent.blocked=False
    result=answer_intake(initial['job_id'],['Omit payments; keep a contact link.'],agent,store)
    assert result['job_id']==initial['job_id'] and result['status']=='AUTONOMOUS_DRAFT_READY'
    context=agent.calls[-1][1]
    assert context['original_request']=='Build a landing page with payment integration.'
    assert context['human_clarifications'][0]['answer']=='Omit payments; keep a contact link.'
    ledger=TaskLedger(store,result['job_id']);intake=next(t for t in ledger.list() if t.task.owner=='requirements')
    assert intake.revision==2 and len(intake.observations)==2
    from pathlib import Path
    assert all(Path(o.checks[0].report).is_file() for o in intake.observations)


def test_help_intent_never_calls_the_app_planner(tmp_path):
    class HelpAgent(Agent):
        def generate(self,schema,*_,**__):
            self.calls.append(schema)
            assert schema is IntakeDecision
            return IntakeDecision.model_validate({'intent':'help','topic':'workflow'})
    agent=HelpAgent(draft())
    result=plan_app('How does this app development workflow work?',agent,JobStore(tmp_path/'jobs.sqlite3'))
    assert result['status']=='REQUEST_ANSWERED' and agent.calls==[IntakeDecision]


def test_controller_created_job_keeps_its_identity_and_operation_history(tmp_path):
    store=JobStore(tmp_path/'jobs.sqlite3');agent=Agent(draft())
    job=store.create({'description':'Build an interactive calculator.','model':agent.model_name,'workflow':'autonomous'})
    store.event(job,'OPERATION_STARTED',{'operation_id':'operation'},update_status=False)
    result=start_planning(job,agent,store)
    assert result['job_id']==job and result['status']=='AUTONOMOUS_DRAFT_READY'
    assert len(store.list_jobs())==1 and result['events'][1]['status']=='OPERATION_STARTED'
    assert agent.calls[-1][1]['original_request']=='Build an interactive calculator.'
    with pytest.raises(ValueError,match='already dispatched'):start_planning(job,agent,store)


@pytest.mark.parametrize('workflow,model',[('typed','qwen2.5-coder:7b'),('autonomous','qwen2.5-coder:3b')])
def test_existing_job_cannot_switch_workflow_or_model(tmp_path,workflow,model):
    store=JobStore(tmp_path/'jobs.sqlite3');agent=Agent(draft())
    job=store.create({'description':'Build an interactive calculator.','model':model,'workflow':workflow})
    with pytest.raises(ValueError):start_planning(job,agent,store)
    assert not agent.calls and TaskLedger(store,job).list()==[]


def test_planner_receives_real_base_dependencies_and_framework_facts(tmp_path):
    from pathlib import Path
    agent=Agent(draft());store=JobStore(tmp_path/'jobs.sqlite3')
    result=plan_app('Build a small interactive page.',agent,store)
    assert result['status']=='AUTONOMOUS_DRAFT_READY'
    context=agent.calls[-1][1]
    capabilities=context['runtime_capabilities']
    package=json.loads((Path(__file__).resolve().parents[1]/'templates/task-app/package.json').read_text())
    assert capabilities['dependencies']==package['dependencies']
    assert capabilities['dev_dependencies']==package['devDependencies']
    assert capabilities['framework_entrypoints']['optional_http_handler'].endswith('/route.ts')
    assert capabilities['test_frameworks_available']==[]
    assert context['original_request']=='Build a small interactive page.'
