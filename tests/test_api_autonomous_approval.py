from pathlib import Path
import hashlib
from uuid import uuid4

import pytest

from forge.autonomous_planning import plan_app
from forge.autonomous_review import request_changes
from forge.dashboard_worker import execute
from forge.workspace import source_fingerprint
from test_api import client,fake_submit,session
from test_autonomous_planning import Agent,draft


def prepare(browser,app):
    agent=Agent(draft());record=plan_app('Build a small interactive page.',agent,app.state.store)
    job=record['job_id'];event=record['events'][-1]
    report=browser.get(f'/api/jobs/{job}/reports/{event["sequence"]}').json()
    return job,agent,report['review_fingerprint'],event['sequence']


def send(browser,headers,job,action,**extra):
    view=browser.get('/api/jobs/'+job).json()
    return browser.post(f'/api/jobs/{job}/actions',headers=headers,json={
        'action':action,'request_id':uuid4().hex,'expected_sequence':view['last_sequence'],**extra})


def test_loaded_proposal_and_explicit_consent_are_required_before_build_dispatch(client,monkeypatch):
    import forge.autonomous_build as build
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    job,agent,token,_=prepare(browser,app);started=[]
    def start(job_id,*args,**kwargs):
        assert app.state.store.read(job_id)['status']=='AUTONOMOUS_APPROVED'
        started.append(job_id);return app.state.store.read(job_id)
    monkeypatch.setattr(build,'build_app',start)
    assert send(browser,headers,job,'approve',fingerprint='f'*64,approved=True).status_code==409
    assert send(browser,headers,job,'approve',fingerprint=token).status_code==422
    assert not calls and not started
    assert send(browser,headers,job,'approve',fingerprint=token,approved=True).status_code==202
    execute(job,'approve',calls[-1][2],app.state.store,agent)
    assert started==[job] and app.state.store.read(job)['events'][-1]['payload']['actor']=='local_dashboard'


def test_decline_records_decision_without_starting_generation(client,monkeypatch):
    import forge.autonomous_build as build
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    job,agent,token,_=prepare(browser,app)
    monkeypatch.setattr(build,'build_app',lambda *_:pytest.fail('A rejection cannot build'))
    assert send(browser,headers,job,'reject',fingerprint=token).status_code==202
    result=execute(job,'reject',calls[-1][2],app.state.store,agent)
    assert result['status']=='AUTONOMOUS_REJECTED'
    assert send(browser,headers,job,'continue').status_code==409


def test_review_feedback_is_validated_and_replans_in_the_same_job(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    job,agent,token,_=prepare(browser,app)
    assert send(browser,headers,job,'revise_plan',fingerprint=token,feedback=' ').status_code==422
    assert send(browser,headers,job,'revise_plan',fingerprint=token,feedback='Add a Reset button.').status_code==202
    result=execute(job,'revise_plan',calls[-1][2],app.state.store,agent)
    assert result['job_id']==job and result['status']=='AUTONOMOUS_DRAFT_READY'
    assert agent.calls[-1][1]['human_review_feedback']==['Add a Reset button.']


def test_old_report_cannot_supply_a_new_decision_token_after_replanning(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    job,agent,old_token,old_sequence=prepare(browser,app)
    request_changes(job,agent,app.state.store,old_token,'Add a Reset button.',actor='test_operator')
    old=browser.get(f'/api/jobs/{job}/reports/{old_sequence}')
    assert old.status_code==200 and 'review_fingerprint' not in old.json()
    assert browser.get('/api/jobs/'+job).json()['review_fingerprint']!=old_token
    assert send(browser,headers,job,'approve',fingerprint=old_token,approved=True).status_code==409
    assert calls==[]


def test_worker_cannot_build_without_recorded_consent_or_approval(client):
    browser,app=client;session(browser);job,agent,token,_=prepare(browser,app)
    with pytest.raises(ValueError,match='explicit approval'):
        execute(job,'approve',{'fingerprint':token},app.state.store,agent)
    with pytest.raises(ValueError,match='requires an approved'):
        execute(job,'continue',{},app.state.store,agent)
    assert app.state.store.read(job)['status']=='AUTONOMOUS_DRAFT_READY'


def test_changed_source_is_not_presented_as_current_build_evidence(client,tmp_path):
    browser,app=client;session(browser)
    job=app.state.store.create({'workflow':'autonomous'})
    root=tmp_path/'workspace'/job;root.mkdir(parents=True)
    path=root/'page.txt';path.write_text('verified fixture source')
    app.state.store.event(job,'AUTONOMOUS_BUILD_CHECKS_PASSED',{'source_fingerprint':source_fingerprint(root)})
    assert browser.get('/api/jobs/'+job).json()['build_evidence_current'] is True
    path.write_text('changed after verification')
    assert browser.get('/api/jobs/'+job).json()['build_evidence_current'] is False


def test_managed_approval_continues_from_build_to_independent_qa(client,monkeypatch):
    import forge.autonomous_build as build
    import forge.autonomous_testing as testing
    browser,app=client;session(browser);job,agent,token,_=prepare(browser,app);calls=[]
    def generated(job_id,*_):
        app.state.store.event(job_id,'AUTONOMOUS_BUILD_CHECKS_PASSED',{'source_fingerprint':'a'*64})
        return app.state.store.read(job_id)
    def checked(job_id,*_):
        assert app.state.store.read(job_id)['status']=='AUTONOMOUS_BUILD_CHECKS_PASSED'
        calls.append(job_id);app.state.store.event(job_id,'AUTONOMOUS_APP_CHECKS_PASSED',{'scope':'selected fixture checks'})
        return app.state.store.read(job_id)
    monkeypatch.setattr(build,'build_app',generated);monkeypatch.setattr(testing,'test_app',checked)
    result=execute(job,'approve',{'fingerprint':token,'approved':True},app.state.store,agent)
    assert result['status']=='AUTONOMOUS_APP_CHECKS_PASSED' and calls==[job]
    with pytest.raises(ValueError,match='approval'):
        execute(job,'preview_start',{},app.state.store,agent)


def test_test_resume_requires_a_saved_safe_qa_task(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    job,_,_,_=prepare(browser,app)
    app.state.store.event(job,'AUTONOMOUS_TEST_PAUSED',{'task_id':'missing','reason':'Interrupted fixture'})
    assert send(browser,headers,job,'resume_tests').status_code==409 and not calls


@pytest.mark.parametrize('approved,status',[(False,422),(True,409)])
def test_autonomous_preview_requires_consent_and_current_evidence_before_dispatch(client,monkeypatch,approved,status):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    job,_,_,_=prepare(browser,app)
    app.state.store.event(job,'AUTONOMOUS_APP_CHECKS_PASSED',{'scope':'An assertion is not evidence'})
    assert send(browser,headers,job,'preview_start',approved=approved).status_code==status
    assert not calls


def test_frozen_contract_report_rejects_changed_bytes(client,tmp_path):
    browser,app=client;session(browser);job,_,_,_=prepare(browser,app)
    path=tmp_path/'artifacts/contract.json';path.parent.mkdir(exist_ok=True)
    path.write_text('{"suite": {}}',encoding='utf-8')
    app.state.store.event(job,'AUTONOMOUS_ACCEPTANCE_FROZEN',{'report':str(path),
        'contract_fingerprint':hashlib.sha256(path.read_bytes()).hexdigest()},update_status=False)
    sequence=app.state.store.read(job)['events'][-1]['sequence']
    assert browser.get(f'/api/jobs/{job}/reports/{sequence}').status_code==200
    path.write_text('{}',encoding='utf-8')
    assert browser.get(f'/api/jobs/{job}/reports/{sequence}').status_code==409


@pytest.mark.parametrize('action,options',[('retry_coverage',{'retry_coverage':True}),('test_selected',{'run_selected':True})])
def test_blocked_coverage_routes_to_the_requested_verification_action(client,monkeypatch,action,options):
    import forge.autonomous_testing as testing
    from forge.autonomous_review import decide_plan
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    job,agent,token,_=prepare(browser,app);decide_plan(job,app.state.store,token,approved=True,actor='test_operator')
    app.state.store.event(job,'AUTONOMOUS_CHECKS_BLOCKED',{'reason':'Review unsupported claim'})
    received=[]
    def retry(job_id,*args,**kwargs):received.append(kwargs);return app.state.store.read(job_id)
    monkeypatch.setattr(testing,'test_app',retry)
    assert send(browser,headers,job,action).status_code==202
    execute(job,action,calls[-1][2],app.state.store,agent)
    assert received==[options]
    assert send(browser,headers,job,'preview_start').status_code==409
