import pytest

from forge.persistence import JobStore
from forge.operations import OperationManager
from test_api import client,session,fake_submit
from test_operations import manager_fixture


def test_delete_hides_run_preserves_history_and_allows_restore(tmp_path,monkeypatch):
    store=JobStore(tmp_path/'jobs.db');job=store.create();store.event(job,'PLAN_REVIEW',{'fingerprint':'a'*64})
    manager=OperationManager(store);monkeypatch.setattr(manager,'cleanup_job',lambda *_:None)
    result=manager.delete(job)
    assert result['recoverable']
    assert not store.list_jobs()
    with pytest.raises(KeyError):store.read(job)
    with pytest.raises(KeyError):store.event(job,'BUILDING',{})
    assert store.list_jobs(deleted=True)[0]['job_id']==job
    restored=store.restore(job)
    assert restored['status']=='PLAN_REVIEW'
    assert restored['events'][0]['status']=='RECEIVED'
    manager.close()


def test_delete_active_run_stops_worker_before_hiding(tmp_path,monkeypatch):
    from uuid import uuid4
    store,job,manager=manager_fixture(tmp_path,monkeypatch)
    op=manager.submit(job,'plan',{},uuid4().hex,store.read(job)['events'][-1]['sequence'])
    process=manager.processes[op['id']]
    manager.delete(job)
    assert process.poll() is not None
    assert store.list_jobs()==[]
    assert store.restore(job)['status']=='INTERRUPTED'
    manager.close()


def test_failed_cleanup_does_not_hide_run(tmp_path,monkeypatch):
    store=JobStore(tmp_path/'jobs.db');job=store.create();manager=OperationManager(store)
    def fail(*_):raise RuntimeError('Cannot stop preview')
    monkeypatch.setattr(manager,'cleanup_job',fail)
    with pytest.raises(RuntimeError):manager.delete(job)
    assert store.read(job)['deleted_at'] is None
    manager.close()


def test_delete_api_requires_csrf_and_deleted_source_is_unavailable(client):
    browser,app=client;job=app.state.store.create()
    headers=session(browser)
    assert browser.post(f'/api/jobs/{job}/delete',json={}).status_code==403
    assert browser.post(f'/api/jobs/{job}/delete',json={},headers=headers).status_code==200
    assert browser.get(f'/api/jobs/{job}').status_code==404
    assert browser.get(f'/api/jobs/{job}/source.zip').status_code==404
    assert browser.get('/api/trash').json()['jobs'][0]['job_id']==job
    assert browser.post(f'/api/jobs/{job}/delete',json={},headers=headers).status_code==200
    assert browser.post(f'/api/jobs/{job}/restore',json={},headers=headers).status_code==200
    assert browser.get(f'/api/jobs/{job}').status_code==200


def test_old_creation_retry_cannot_resurrect_deleted_run(client,monkeypatch):
    from uuid import uuid4
    browser,app=client;headers=session(browser);fake_submit(app,monkeypatch)
    body={'description':'Create a local task management app','request_id':uuid4().hex}
    created=browser.post('/api/jobs',json=body,headers=headers).json()
    assert browser.post(f'/api/jobs/{created["job_id"]}/delete',json={},headers=headers).status_code==200
    assert browser.post('/api/jobs',json=body,headers=headers).status_code==409
    assert browser.get('/api/jobs').json()['jobs']==[]
