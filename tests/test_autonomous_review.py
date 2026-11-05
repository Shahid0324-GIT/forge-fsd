from pathlib import Path

import pytest

from forge import autonomous_planning as planning
from forge.autonomous_review import approved_review,decide_plan,review_snapshot,request_changes
from forge.persistence import JobStore
from forge.tasks import TaskLedger
from test_autonomous_planning import Agent,draft


@pytest.fixture
def proposal(tmp_path):
    store=JobStore(tmp_path/'artifacts/jobs.sqlite3');agent=Agent(draft())
    record=planning.plan_app('Build a small interactive page.',agent,store)
    return store,record['job_id'],agent


def test_approval_binds_reviewed_source_manifest_inputs_and_runtime_without_building(proposal):
    store,job,agent=proposal;review=review_snapshot(job,store)
    snapshot=Path(review['report']);before=snapshot.read_bytes()
    result=decide_plan(job,store,review['fingerprint'],approved=True,actor='test_operator')
    assert result['status']=='AUTONOMOUS_APPROVED'
    assert approved_review(job,store)==review and snapshot.read_bytes()==before
    assert result['events'][-1]['payload']['app_execution']=='NOT_RUN'
    assert len(agent.calls)==3 and len(TaskLedger(store,job).list())==3
    assert any(task.task.owner=='implementation_reviewer' and task.status=='completed'
        for task in TaskLedger(store,job).list())
    with pytest.raises(ValueError,match='Only the current proposal'):
        decide_plan(job,store,review['fingerprint'],approved=True,actor='test_operator')


def test_ordinary_operation_events_do_not_change_the_review_token(proposal):
    store,job,_=proposal;review=review_snapshot(job,store)
    store.event(job,'OPERATION_FINISHED',{'outcome':'SUCCEEDED'},update_status=False)
    assert review_snapshot(job,store)['fingerprint']==review['fingerprint']


@pytest.mark.parametrize('changed',['candidate','snapshot','task','runtime'])
def test_changes_invalidate_review_before_approval(proposal,changed,monkeypatch):
    store,job,_=proposal;review=review_snapshot(job,store)
    if changed in {'candidate','snapshot'}:
        path=Path(review['report']) if changed=='snapshot' else Path(review['report']).parent/'candidate.json'
        path.write_text(draft().model_copy(update={'design':'A changed design'}).model_dump_json(),encoding='utf-8')
    if changed=='task':
        ledger=TaskLedger(store,job);state=ledger.read(review['binding']['task_id'])
        ledger.revise(state,state.task.model_copy(update={'inputs':{'original_request':'A changed user request'}}))
    if changed=='runtime':monkeypatch.setattr(planning,'capability_fingerprint',lambda:'f'*64)
    with pytest.raises(ValueError):decide_plan(job,store,review['fingerprint'],approved=True,actor='test_operator')
    assert store.read(job)['status']=='AUTONOMOUS_DRAFT_READY'


def test_reject_and_wrong_token_never_authorize_builds(proposal):
    store,job,_=proposal;review=review_snapshot(job,store)
    with pytest.raises(ValueError,match='reviewed proposal changed'):
        decide_plan(job,store,'0'*64,approved=True,actor='test_operator')
    with pytest.raises(ValueError,match='explicit'):
        decide_plan(job,store,review['fingerprint'],approved='yes',actor='test_operator')
    decide_plan(job,store,review['fingerprint'],approved=False,actor='test_operator')
    assert store.read(job)['status']=='AUTONOMOUS_REJECTED'
    with pytest.raises(ValueError):approved_review(job,store)


def test_cancelled_job_and_changed_approved_source_cannot_reuse_approval(proposal):
    store,job,_=proposal;review=review_snapshot(job,store)
    decide_plan(job,store,review['fingerprint'],approved=True,actor='test_operator')
    Path(review['report']).write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError):approved_review(job,store)
    store.event(job,'CANCELLED',{})
    with pytest.raises(ValueError,match='not authorized'):approved_review(job,store)


def test_requested_changes_recheck_scope_preserve_history_and_require_new_approval(proposal):
    store,job,agent=proposal;old=review_snapshot(job,store);saved=Path(old['report']).read_bytes()
    old_checks=TaskLedger(store,job).read(old['binding']['task_id']).observations[-1].checks[0].report
    checks_before=Path(old_checks).read_bytes()
    agent.proposal=draft().model_copy(update={'design':'The updated design includes a reset button.'})
    result=request_changes(job,agent,store,old['fingerprint'],'Add a Reset button.',actor='test_operator')
    new=review_snapshot(job,store)
    assert result['job_id']==job and result['status']=='AUTONOMOUS_DRAFT_READY'
    assert new['fingerprint']!=old['fingerprint'] and new['binding']['inputs']['original_request']==old['binding']['inputs']['original_request']
    assert agent.calls[-1][1]['human_review_feedback']==['Add a Reset button.']
    context=[data for schema,data in agent.calls if schema is planning.AppDraft][-1]
    assert context['latest_proposal'] is None
    assert Path(old['report']).read_bytes()==saved and Path(old_checks).read_bytes()==checks_before
    with pytest.raises(ValueError):decide_plan(job,store,old['fingerprint'],approved=True,actor='test_operator')
    assert not any(e['status']=='AUTONOMOUS_APPROVED' for e in result['events'])


def test_new_scope_in_review_feedback_returns_to_intake_before_planning(proposal):
    store,job,agent=proposal;review=review_snapshot(job,store);agent.blocked=True
    result=request_changes(job,agent,store,review['fingerprint'],'Add payment integration.',actor='test_operator')
    assert result['status']=='AUTONOMOUS_INPUT_NEEDED'
    assert agent.calls[-1][1]['human_review_feedback']==['Add payment integration.']
