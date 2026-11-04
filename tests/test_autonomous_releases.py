from pathlib import Path
import json
import shutil

import pytest

import forge.releases as releases
from forge.autonomous_testing import test_app as check_app
from forge.tasks import TaskLedger
from forge.workspace import source_fingerprint
from test_autonomous_build import setup
from test_autonomous_testing import ready,build_checks,browsers


@pytest.fixture
def verified_app(ready,monkeypatch):
    store,job,qa_agent,boundary,review=ready
    check_app(job,qa_agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    actual=releases.PROJECT;project=boundary.parent
    shutil.copytree(actual/'templates',project/'templates')
    shutil.copytree(actual/'tests/acceptance',project/'tests/acceptance')
    monkeypatch.setattr(releases,'PROJECT',project)
    class Agent:
        model_name='qwen2.5-coder:7b'
        def __init__(self):self.calls=[]
        def generate(self,schema,instruction,data):
            self.calls.append((schema,data))
            notes={'summary':'Locked build and homepage smoke only.','limitations':['Local browser checks are not rerun in hosted CI.']}
            if schema is releases.DeploymentNotes:notes['target']='vercel'
            return schema.model_validate(notes)
    return store,job,boundary,Agent()


def test_verified_autonomous_app_gets_bound_release_roles_and_explicit_limited_ci(verified_app):
    store,job,boundary,agent=verified_app;before=source_fingerprint(boundary/job)
    record=releases.prepare_release(job,agent,store,'person/counter-demo')
    event=record['events'][-1]['payload'];report,bundle=releases.reviewed_release(job,store,event['release_fingerprint'])
    assert source_fingerprint(boundary/job)==before==report['source_fingerprint']
    assert report['autonomous'] and report['deployment_allowed'] and not report['ci_executed'] and not report['cloud_deployed']
    assert 'homepage' in report['ci_policy'] and 'not replayed' in report['limitations'][0]
    assert json.loads((bundle/'.forge/contract.json').read_text())['requirements']['scenarios']==[]
    assert json.loads((bundle/'.forge/contract.json').read_text())['verification_scope']=='build-homepage-smoke'
    assert (bundle/'.github/workflows/app-ci.yml').exists() and (bundle/'.github/workflows/deploy.yml').exists()
    assert 'homepage HTTP smoke (browser QA ran locally)' in (bundle/'.github/workflows/app-ci.yml').read_text()
    roles={t.task.owner:t for t in TaskLedger(store,job).list() if t.task.owner in {'ci_agent','deployment_agent'}}
    assert set(roles)=={'ci_agent','deployment_agent'} and all(t.status=='completed' for t in roles.values())
    assert roles['deployment_agent'].task.parent_id==roles['ci_agent'].task.id
    assert all(t.task.inputs['source_fingerprint']==before for t in roles.values())
    assert agent.calls[1][1]['ci_agent']==report['ci_agent']
    with pytest.raises(ValueError,match='approval'):releases.publish_release(job,store,event['release_fingerprint'])
    agent.calls.clear()
    releases.prepare_release(job,agent,store,'person/counter-demo')
    assert not agent.calls and sum(t.task.owner=='ci_agent' for t in TaskLedger(store,job).list())==1


@pytest.mark.parametrize('invalid',['stale','partial'])
def test_autonomous_release_rejects_incomplete_evidence_before_model_calls(verified_app,invalid):
    store,job,boundary,agent=verified_app
    if invalid=='stale':(boundary/job/'app/page.tsx').write_text('changed')
    else:store.event(job,'AUTONOMOUS_CHECKS_BLOCKED',{'selected_checks_passed':True})
    with pytest.raises(ValueError,match='current'):releases.prepare_release(job,agent,store,'person/demo')
    assert not agent.calls


def test_failed_release_role_is_recorded_without_a_reviewable_bundle(verified_app):
    store,job,_,agent=verified_app
    def fail(*args):raise ValueError('Invalid notes')
    agent.generate=fail
    with pytest.raises(ValueError,match='Invalid notes'):releases.prepare_release(job,agent,store,'person/demo')
    roles=[t for t in TaskLedger(store,job).list() if t.task.owner=='ci_agent']
    assert len(roles)==1 and roles[0].status=='paused' and roles[0].observations[-1].error
    assert not any(e['status']=='RELEASE_REVIEW' for e in store.read(job)['events'])
    replacement=type(agent)()
    releases.prepare_release(job,replacement,store,'person/demo')
    roles=[t for t in TaskLedger(store,job).list() if t.task.owner=='ci_agent']
    assert len(roles)==1 and roles[0].status=='completed'
    assert replacement.calls[0][1]['previous_role_errors']
