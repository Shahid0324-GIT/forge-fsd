import json
from pathlib import Path
from uuid import uuid4

import pytest

from forge.autonomous_planning import plan_app
from forge.dashboard_worker import execute
from forge.tasks import TaskLedger
from test_api import client,fake_submit,session
from test_autonomous_planning import Agent,draft


def test_managed_autonomous_plan_keeps_identity_and_returns_integrity_checked_proposal(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    body={'description':'Build a small interactive calculator.','model':'qwen2.5-coder:7b',
        'workflow':'autonomous','request_id':uuid4().hex}
    created=browser.post('/api/jobs',headers=headers,json=body)
    assert created.status_code==202
    job=created.json()['job_id'];agent=Agent(draft())
    result=execute(job,'plan',{'description':'Do not replace the saved request'},app.state.store,agent)
    assert result['job_id']==job and result['status']=='AUTONOMOUS_DRAFT_READY'
    assert len(app.state.store.list_jobs())==1 and agent.calls[-1][1]['original_request']==body['description']
    view=browser.get('/api/jobs/'+job).json()
    assert view['workflow']=='autonomous' and view['title']=='A small app'
    event=next(e for e in reversed(result['events']) if e['status']=='AUTONOMOUS_DRAFT_READY')
    url=f'/api/jobs/{job}/reports/{event["sequence"]}'
    assert browser.get(url).json()['design']==draft().design
    path=Path(event['payload']['report']);changed=json.loads(path.read_text());changed['design']='Changed after planning'
    path.write_text(json.dumps(changed),encoding='utf-8')
    assert browser.get(url).status_code==409
    assert len(calls)==1


def test_request_identity_cannot_switch_workflows(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    body={'description':'Build a small interactive calculator.','request_id':uuid4().hex}
    first=browser.post('/api/jobs',headers=headers,json=body)
    assert browser.get('/api/jobs/'+first.json()['job_id']).json()['workflow']=='typed'
    assert browser.post('/api/jobs',headers=headers,json={**body,'workflow':'autonomous'}).status_code==409
    assert len(calls)==1 and len(app.state.store.list_jobs())==1


def test_autonomous_clarification_uses_same_job_and_original_request(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    agent=Agent(draft(),blocked=True)
    initial=plan_app('Build a landing page with payment integration.',agent,app.state.store)
    job=initial['job_id'];view=browser.get('/api/jobs/'+job).json()
    payload={'action':'answer','request_id':uuid4().hex,'expected_sequence':view['last_sequence'],'answers':[]}
    assert browser.post(f'/api/jobs/{job}/actions',headers=headers,json=payload).status_code==422
    payload['answers']=['Omit payments; keep a contact link.']
    assert browser.post(f'/api/jobs/{job}/actions',headers=headers,json=payload).status_code==202
    agent.blocked=False
    result=execute(job,'answer',calls[-1][2],app.state.store,agent)
    assert result['status']=='AUTONOMOUS_DRAFT_READY' and result['job_id']==job
    assert agent.calls[-1][1]['human_clarifications'][0]['answer']==payload['answers'][0]


@pytest.mark.parametrize('interrupted',[False,True])
def test_resume_requires_a_safe_saved_planning_pause(client,monkeypatch,interrupted):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    bad=draft();bad.files[0].path='package.json';agent=Agent(bad)
    initial=plan_app('Build a small interactive page.',agent,app.state.store,action_limit=1)
    job=initial['job_id'];ledger=TaskLedger(app.state.store,job)
    if interrupted:
        state=ledger.read(initial['events'][-1]['payload']['task_id'])
        state=ledger.reserve_action(ledger.start(ledger.resume(state,additional_actions=1)),'planner')
        ledger.pause(state,'Unreconciled interrupted model call')
    view=browser.get('/api/jobs/'+job).json()
    assert view['planning_resumable'] is not interrupted
    response=browser.post(f'/api/jobs/{job}/actions',headers=headers,json={
        'action':'resume_planning','request_id':uuid4().hex,'expected_sequence':view['last_sequence']})
    if interrupted:
        assert response.status_code==409 and not calls
    else:
        assert response.status_code==202
        agent.proposal=draft()
        result=execute(job,'resume_planning',{},app.state.store,agent)
        assert result['job_id']==job and result['status']=='AUTONOMOUS_DRAFT_READY'


@pytest.mark.parametrize('action,error',[('preview_start','approval'),('publish_release','approval')])
def test_autonomous_jobs_preserve_preview_consent_and_publication_boundary(client,action,error):
    _,app=client;agent=Agent(draft())
    result=plan_app('Build a small interactive page.',agent,app.state.store)
    with pytest.raises(ValueError,match=error):
        execute(result['job_id'],action,{},app.state.store,agent)
