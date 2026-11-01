import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from forge.api import create_app
from forge.persistence import now


@pytest.fixture
def client(tmp_path,monkeypatch):
    import forge.api as module
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    app=create_app(tmp_path/'jobs.db')
    monkeypatch.setattr(app.state.operations,'cleanup_job',lambda *_:None)
    with TestClient(app,base_url='http://127.0.0.1:8787') as client:
        yield client,app


def session(client):
    return {'X-Forge-CSRF':client.get('/api/session').json()['csrf']}


def fake_submit(app,monkeypatch):
    calls=[]
    def submit(job,action,payload,request_id,expected_sequence):
        calls.append((job,action,payload));op=uuid4().hex
        with app.state.store.connect() as db:
            db.execute('INSERT INTO operations(id,job_id,request_id,action,status,started_at) VALUES (?,?,?,?,?,?)',(op,job,request_id,action,'SUCCEEDED',now()))
        return app.state.operations.read(op)
    monkeypatch.setattr(app.state.operations,'submit',submit)
    return calls


def test_session_required_for_api(client):
    browser,app=client
    assert browser.get('/api/jobs').status_code==401
    session(browser)
    assert browser.get('/api/jobs').status_code==200


def test_app_release_actions_require_review_and_separate_consent(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    job=app.state.store.create();app.state.store.event(job,'SECURITY_PASSED',{})
    sequence=app.state.store.read(job)['events'][-1]['sequence']
    def send(action,**extra):
        return browser.post(f'/api/jobs/{job}/actions',headers=headers,json={
            'action':action,'request_id':str(uuid4()),'expected_sequence':sequence,**extra})
    assert send('prepare_release',repository='https://github.com/a/b').status_code==422
    assert send('prepare_release',repository='person/new-app').status_code==202
    assert send('publish_release',fingerprint='a'*64).status_code==422
    assert send('deploy_release',fingerprint='a'*64).status_code==422
    assert send('publish_release',fingerprint='a'*64,approved=True).status_code==202
    assert calls[-1][2]=={'fingerprint':'a'*64,'approved':True}


def test_browser_action_rejects_apps_without_a_trusted_profile(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    job=app.state.store.create();app.state.store.event(job,'FUNCTIONALLY_VERIFIED',{})
    result=browser.post(f'/api/jobs/{job}/actions',headers=headers,json={
        'action':'browser_check','request_id':uuid4().hex,'expected_sequence':app.state.store.read(job)['events'][-1]['sequence']})
    assert result.status_code==409 and 'profile' in result.json()['detail']
    assert calls==[]


def test_cross_origin_including_generated_app_is_denied(client):
    browser,app=client
    headers=session(browser)
    for origin in ['https://attacker.example','http://127.0.0.1:56471','null']:
        assert browser.get('/api/session',headers={'Origin':origin}).status_code==403
        assert browser.post('/api/jobs',json={'description':'Build a task app','request_id':uuid4().hex},headers={**headers,'Origin':origin}).status_code==403


def test_mutation_requires_csrf_and_local_host(client):
    browser,app=client;session(browser)
    body={'description':'Build a task app','request_id':uuid4().hex}
    assert browser.post('/api/jobs',json=body).status_code==403
    assert browser.get('/api/session',headers={'Host':'attacker.example'}).status_code in {400,403}


def test_new_job_retries_are_idempotent(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    body={'description':'Build a local task management app','request_id':uuid4().hex}
    first=browser.post('/api/jobs',json=body,headers=headers)
    second=browser.post('/api/jobs',json=body,headers=headers)
    assert first.status_code==202
    assert second.json()['job_id']==first.json()['job_id']
    assert len(calls)==1


def test_approval_requires_current_fingerprint(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    store=app.state.store;job=store.create();store.event(job,'PLAN_REVIEW',{'fingerprint':'a'*64})
    sequence=store.read(job)['events'][-1]['sequence']
    body={'action':'approve','request_id':uuid4().hex,'expected_sequence':sequence,'fingerprint':'b'*64}
    assert browser.post(f'/api/jobs/{job}/actions',json=body,headers=headers).status_code==409
    body['fingerprint']='a'*64
    assert browser.post(f'/api/jobs/{job}/actions',json=body,headers=headers).status_code==202
    assert len(calls)==1


def test_preview_requires_explicit_approval(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    store=app.state.store;job=store.create();store.event(job,'SECURITY_PASSED',{})
    body={'action':'preview_start','request_id':uuid4().hex,'expected_sequence':store.read(job)['events'][-1]['sequence']}
    assert browser.post(f'/api/jobs/{job}/actions',json=body,headers=headers).status_code==422
    assert calls==[]


def test_report_endpoint_rejects_arbitrary_host_path(client,tmp_path):
    browser,app=client;session(browser)
    store=app.state.store;job=store.create();outside=tmp_path/'outside.json';outside.write_text('{"sensitive":true}')
    store.event(job,'REPORT_CREATED',{'report':str(outside)},update_status=False)
    event=store.read(job)['events'][-1]
    assert browser.get(f'/api/jobs/{job}/reports/{event["sequence"]}').status_code==403


def test_source_zip_excludes_environment_values(client,tmp_path):
    browser,app=client;session(browser);job=app.state.store.create()
    root=tmp_path/'workspace'/job;root.mkdir(parents=True)
    (root/'package.json').write_text('{}');(root/'.env').write_text('SECRET=private');(root/'.env.example').write_text('NAME=placeholder')
    response=browser.get(f'/api/jobs/{job}/source.zip')
    assert response.status_code==200
    import io,zipfile
    names=zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert '.env' not in names and '.env.example' in names


def test_event_cursor_replays_only_new_records(client):
    browser,app=client;session(browser);store=app.state.store;job=store.create()
    cursor=store.read(job)['events'][-1]['sequence']
    store.event(job,'PLANNING',{'delegated_to':'architect_agent'})
    assert [e['status'] for e in store.events_after(job,cursor)]==['PLANNING']


def test_shutdown_requires_session_and_csrf(client):
    browser,app=client
    assert browser.post('/api/shutdown',json={}).status_code==401
    session(browser)
    assert browser.post('/api/shutdown',json={}).status_code==403


def test_shutdown_without_launcher_callback_is_rejected(client):
    browser,app=client;headers=session(browser)
    assert browser.post('/api/shutdown',json={},headers=headers).status_code==409
