import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


spec=importlib.util.spec_from_file_location('flow_evaluation',Path(__file__).resolve().parents[1]/'scripts/evaluate_autonomous_flow.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


def record(status):return {'job_id':'a'*32,'status':status}


def test_flow_stops_at_build_pause_without_running_qa_or_touching_approval(tmp_path,monkeypatch):
    store=SimpleNamespace(path=tmp_path/'jobs.sqlite3');calls=[]
    monkeypatch.setattr(runner,'review_snapshot',lambda *args: {'fingerprint':'review','draft':{}})
    def approve(*args,**kwargs):
        assert kwargs['actor']=='internal_evaluation' and kwargs['approved'] is True
        calls.append('approve');return record('AUTONOMOUS_APPROVED')
    monkeypatch.setattr(runner,'decide_plan',approve)
    monkeypatch.setattr(runner,'build_app',lambda *a,**k: calls.append('build') or record('AUTONOMOUS_BUILD_PAUSED'))
    monkeypatch.setattr(runner,'test_app',lambda *a,**k: (_ for _ in ()).throw(AssertionError('QA cannot run after failed build')))
    result=runner.run_flow(record('AUTONOMOUS_DRAFT_READY'),object(),store,tmp_path/'workspace')
    assert result['status']=='AUTONOMOUS_BUILD_PAUSED' and calls==['approve','build']


def test_resume_keeps_saved_test_stage_instead_of_replanning_or_regenerating(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(runner,'build_app',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Do not regenerate built source')))
    monkeypatch.setattr(runner,'resume_planning',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Do not replan frozen checks')))
    def check(*args,**kwargs):
        calls.append(kwargs);return record('AUTONOMOUS_APP_CHECKS_PASSED')
    monkeypatch.setattr(runner,'test_app',check)
    result=runner.run_flow(record('AUTONOMOUS_TEST_PAUSED'),object(),object(),tmp_path,resume=True)
    assert result['status']=='AUTONOMOUS_APP_CHECKS_PASSED' and len(calls)==1
    assert calls[0]['resume'] is True


def test_pause_requires_explicit_resume_and_partial_coverage_is_preserved(tmp_path,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('Must not continue a paused or partially covered run')
    monkeypatch.setattr(runner,'test_app',forbidden);monkeypatch.setattr(runner,'build_app',forbidden)
    for status in ['AUTONOMOUS_TEST_PAUSED','AUTONOMOUS_BUILD_PAUSED','AUTONOMOUS_CHECKS_BLOCKED']:
        assert runner.run_flow(record(status),object(),object(),tmp_path)['status']==status


def test_evaluation_rejects_success_status_without_current_execution_evidence(tmp_path,monkeypatch):
    import sys
    monkeypatch.setattr(runner,'EVIDENCE',tmp_path/'evidence');monkeypatch.setattr(runner,'BOUNDARY',tmp_path/'workspace')
    monkeypatch.setattr(sys,'argv',['evaluate_autonomous_flow','--case','notes'])
    monkeypatch.setattr(runner,'OllamaAgents',lambda model:SimpleNamespace(model_name=model))
    def plan(description,agent,store,**kwargs):
        job=store.create({'description':description,'model':agent.model_name})
        store.event(job,'AUTONOMOUS_APP_CHECKS_PASSED',{})
        return store.read(job)
    monkeypatch.setattr(runner,'plan_app',plan)
    monkeypatch.setattr(runner,'evidence_current',lambda *a,**k:False)
    assert runner.main()==1
    summary=json.loads(next((tmp_path/'evidence').rglob('result.json')).read_text())
    assert summary['status']=='AUTONOMOUS_APP_CHECKS_PASSED' and summary['passed'] is False


def test_failed_evaluation_retains_generated_source_for_recovery(tmp_path,monkeypatch):
    import sys
    monkeypatch.setattr(runner,'EVIDENCE',tmp_path/'evidence');monkeypatch.setattr(runner,'BOUNDARY',tmp_path/'workspace')
    monkeypatch.setattr(sys,'argv',['evaluate_autonomous_flow','--case','notes'])
    monkeypatch.setattr(runner,'OllamaAgents',lambda model:SimpleNamespace(model_name=model))
    def plan(description,agent,store,**kwargs):
        job=store.create({'description':description,'model':agent.model_name})
        store.event(job,'AUTONOMOUS_APPROVED',{})
        return store.read(job)
    def build(job,agent,store,**kwargs):
        root=kwargs['workspace_boundary']/job;root.mkdir(parents=True)
        (root/'retained.ts').write_text('export const retained=true',encoding='utf-8')
        store.event(job,'AUTONOMOUS_BUILD_PAUSED',{})
        return store.read(job)
    monkeypatch.setattr(runner,'plan_app',plan);monkeypatch.setattr(runner,'build_app',build)
    assert runner.main()==1
    summary=json.loads(next((tmp_path/'evidence').rglob('result.json')).read_text())
    assert (Path(summary['workspace'])/'retained.ts').is_file() and summary['source_preserved']
