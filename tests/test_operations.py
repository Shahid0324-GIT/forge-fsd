import subprocess
import sys
import time
from uuid import uuid4
import json
from types import SimpleNamespace

import pytest

from forge.operations import BusyError,OperationManager
from forge.persistence import JobStore


def manager_fixture(tmp_path,monkeypatch,delay=5):
    import forge.operations as module
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    def spawn(_command,**kwargs):
        return subprocess.Popen([sys.executable,'-c',f'import time; time.sleep({delay})'],**kwargs)
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    manager=OperationManager(store,spawn=spawn)
    monkeypatch.setattr(manager,'cleanup_job',lambda *_:None)
    return store,job,manager


def test_cleanup_finds_orphan_browser_networks_by_owned_labels(tmp_path,monkeypatch):
    import forge.operations as module
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    store.event(job,'AUTONOMOUS_BUILD_CHECKS_PASSED',{'preview':'NOT_APPROVED'})
    manager=OperationManager(store);calls=[]
    def run(args,**_):
        calls.append(args)
        return SimpleNamespace(returncode=0,stdout='owned other' if args[1:3]==['network','ls'] else '',stderr='')
    def inspect(args,**_):
        return json.dumps([{'Name':'forge-browser-net-'+'a'*12,'Labels':{'forge.job':job if args[-1]=='owned' else 'other','forge.role':'browser_verification'}}])
    monkeypatch.setattr(module.subprocess,'run',run);monkeypatch.setattr(module.subprocess,'check_output',inspect)
    manager.cleanup_job(job)
    assert ['docker','network','rm','owned'] in calls
    assert ['docker','network','rm','other'] not in calls


def test_restart_reconciles_owned_resources_without_replaying_work(tmp_path,monkeypatch):
    store=JobStore(tmp_path/'jobs.db');job=store.create();OperationManager(store)
    with store.connect() as db:
        db.execute("INSERT INTO operations(id,job_id,request_id,action,status,started_at) VALUES (?,?,?,?,?,?)",
            (uuid4().hex,job,uuid4().hex,'resume_tests','RUNNING','2026-11-03T00:00:00Z'))
    cleaned=[];monkeypatch.setattr(OperationManager,'cleanup_job',lambda self,current:cleaned.append(current))
    manager=OperationManager(store)
    assert cleaned==[job] and not manager.active() and store.read(job)['status']=='INTERRUPTED'


def test_failed_owned_resource_cleanup_is_visible_on_cancellation(tmp_path,monkeypatch):
    import forge.operations as module
    store=JobStore(tmp_path/'jobs.db');job=store.create();manager=OperationManager(store)
    def run(args,**_):
        if args[1:3]==['network','ls']:return SimpleNamespace(returncode=0,stdout='owned',stderr='')
        if args[1:3]==['network','rm']:return SimpleNamespace(returncode=1,stdout='',stderr='Denied')
        return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr(module.subprocess,'run',run)
    monkeypatch.setattr(module.subprocess,'check_output',lambda *args,**kwargs:json.dumps([{
        'Name':'forge-browser-net-'+'a'*12,'Labels':{'forge.job':job,'forge.role':'browser_verification'}}]))
    result=manager.cancel(job)
    assert result['status']=='CANCELLED' and 'Denied' in result['events'][-1]['payload']['cleanup_warning']


def test_operation_deduplication_and_global_worker_lock(tmp_path,monkeypatch):
    store,job,manager=manager_fixture(tmp_path,monkeypatch)
    sequence=store.read(job)['events'][-1]['sequence'];request=uuid4().hex
    try:
        first=manager.submit(job,'plan',{},request,sequence)
        assert manager.submit(job,'plan',{},request,sequence)['id']==first['id']
        another=store.create()
        with pytest.raises(BusyError,match='Another operation'):
            manager.submit(another,'plan',{},uuid4().hex,store.read(another)['events'][-1]['sequence'])
    finally:manager.close()


def test_stale_action_is_rejected_before_process_creation(tmp_path,monkeypatch):
    store,job,manager=manager_fixture(tmp_path,monkeypatch)
    sequence=store.read(job)['events'][-1]['sequence'];store.event(job,'PLANNING',{})
    with pytest.raises(BusyError,match='out of date'):
        manager.submit(job,'plan',{},uuid4().hex,sequence)
    assert not manager.active()
    manager.close()


def test_cancel_terminates_owned_worker_and_preserves_source_history(tmp_path,monkeypatch):
    store,job,manager=manager_fixture(tmp_path,monkeypatch)
    operation=manager.submit(job,'plan',{},uuid4().hex,store.read(job)['events'][-1]['sequence'])
    process=manager.processes[operation['id']]
    manager.cancel(job)
    assert process.poll() is not None
    assert manager.read(operation['id'])['status']=='CANCELLED'
    assert store.read(job)['status']=='CANCELLED'
    assert store.read(job)['events'][0]['status']=='RECEIVED'
    manager.close()


def test_normal_operation_completion_releases_lock(tmp_path,monkeypatch):
    store,job,manager=manager_fixture(tmp_path,monkeypatch,delay=.1)
    operation=manager.submit(job,'plan',{},uuid4().hex,store.read(job)['events'][-1]['sequence'])
    deadline=time.monotonic()+5
    while manager.active() and time.monotonic()<deadline:time.sleep(.05)
    assert manager.read(operation['id'])['status']=='SUCCEEDED'
    assert manager.active()==[]
    assert store.read(job)['status']=='RECEIVED'
    manager.close()


def test_unexpected_worker_exit_does_not_leave_job_running(tmp_path,monkeypatch):
    store,job,manager=manager_fixture(tmp_path,monkeypatch)
    manager._spawn=lambda _command,**kwargs:subprocess.Popen([sys.executable,'-c','raise SystemExit(2)'],**kwargs)
    store.event(job,'BUILDING',{})
    operation=manager.submit(job,'continue',{},uuid4().hex,store.read(job)['events'][-1]['sequence'])
    deadline=time.monotonic()+5
    while manager.active() and time.monotonic()<deadline:time.sleep(.05)
    assert manager.read(operation['id'])['status']=='FAILED'
    assert store.read(job)['status']=='FAILED'
    manager.close()
