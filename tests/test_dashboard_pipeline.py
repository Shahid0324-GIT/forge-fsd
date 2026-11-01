import pytest

import forge.dashboard_worker as worker


class Store:
    def __init__(self):self.record={'status':'APPROVED','events':[]}
    def read(self,job):return self.record
    def event(self,job,status,payload,update_status=True):
        self.record['events'].append({'status':status,'payload':payload})
        if update_status:self.record['status']=status


def test_pipeline_never_skips_failed_checks_or_repair_budget(monkeypatch):
    store=Store();calls=[]
    def stage(name,status):
        def run(*args):calls.append(name);store.record['status']=status;return store.record
        return run
    monkeypatch.setattr(worker,'build_job',stage('build','GENERATED_UNVERIFIED'))
    monkeypatch.setattr(worker,'verify_job',stage('verify','VERIFICATION_FAILED'))
    def repair(*args):
        calls.append('repair');store.event('job','REPAIRING',{});store.record['status']='GENERATED_UNVERIFIED';return store.record
    monkeypatch.setattr(worker,'repair_job',repair)
    monkeypatch.setattr(worker,'security_job',lambda *_:pytest.fail('Security cannot run after failed verification'))
    result=worker.pipeline('job',None,store)
    assert result['status']=='VERIFICATION_FAILED'
    assert calls==['build','verify','repair','verify','repair','verify']


def test_pipeline_stops_before_human_preview_approval(monkeypatch):
    store=Store();calls=[]
    def stage(name,status):
        def run(*args):calls.append(name);store.record['status']=status;return store.record
        return run
    for method,name,status in [('build_job','build','GENERATED_UNVERIFIED'),('verify_job','verify','FUNCTIONALLY_VERIFIED'),('security_job','security','SECURITY_PASSED'),('write_report','report','SECURITY_PASSED')]:
        monkeypatch.setattr(worker,method,stage(name,status))
    monkeypatch.setattr(worker,'start_preview',lambda *_:pytest.fail('Preview requires separate approval'))
    result=worker.pipeline('job',None,store)
    assert result['status']=='SECURITY_PASSED'
    assert calls==['build','verify','security','report']
