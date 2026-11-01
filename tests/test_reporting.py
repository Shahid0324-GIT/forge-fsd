import json
import pytest

from forge.persistence import JobStore
from forge.reporting import ReadinessNotes, write_report
from forge.workspace import source_fingerprint
from test_security import passing_checks


class NotesAgent:
    def generate(self,*args,**kwargs):
        return ReadinessNotes(local_setup=['Use Node 24'],deployment_limitations=['Remote database adapter is not implemented'])


def test_report_cannot_override_missing_security_and_does_not_change_status(tmp_path,monkeypatch):
    import forge.reporting as module
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    root=tmp_path/'workspace'/job;root.mkdir(parents=True);(root/'app.ts').write_text('source')
    result=write_report(job,NotesAgent(),store)
    assert result['status']=='RECEIVED'
    assert result['events'][-1]['status']=='REPORT_CREATED'
    report=json.loads(open(result['events'][-1]['payload']['report']).read())
    assert report['assessment']=='UNVERIFIED'
    assert report['cloud_deployed'] is False


def test_report_uses_current_source_evidence(tmp_path,monkeypatch):
    import forge.reporting as module
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    root=tmp_path/'workspace'/job;root.mkdir(parents=True);(root/'app.ts').write_text('source')
    fingerprint=source_fingerprint(root)
    functional=tmp_path/'functional.json';functional.write_text('{}')
    security=tmp_path/'security.json';security.write_text(json.dumps({'checks':passing_checks(),'source_unchanged':True}))
    store.event(job,'FUNCTIONALLY_VERIFIED',{'report':str(functional),'source_fingerprint':fingerprint})
    store.event(job,'SECURITY_PASSED',{'report':str(security),'source_fingerprint':fingerprint})
    result=write_report(job,NotesAgent(),store)
    report=json.loads(open(result['events'][-1]['payload']['report']).read())
    # An empty functional report is insufficient evidence despite the event label.
    assert report['assessment']=='UNVERIFIED'


@pytest.mark.parametrize('matching',[True,False])
def test_manual_browser_evidence_is_bound_to_source_and_cannot_override_gates(tmp_path,monkeypatch,matching):
    import forge.reporting as module
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    root=tmp_path/'workspace'/job;root.mkdir(parents=True);(root/'app.ts').write_text('source')
    fingerprint=source_fingerprint(root)
    store.event(job,'SOURCE_ADJUSTED',{'actor':'developer_review','reason':'Fixed observed validation defect'},update_status=False)
    store.event(job,'BROWSER_QA_PASSED',{'source_fingerprint':fingerprint if matching else 'stale','browser_cases':5},update_status=False)
    record=write_report(job,NotesAgent(),store)
    report=json.loads(open(record['events'][-1]['payload']['report']).read())
    assert bool(report['manual_browser_checks']) is matching
    assert report['source_adjustments'][0]['actor']=='developer_review'
    assert report['assessment']=='UNVERIFIED'
