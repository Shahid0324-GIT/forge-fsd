import json

import pytest

from forge.autonomous_review import approved_review
from forge.autonomous_testing import test_app as run_tests,evidence_current
from forge.execution_models import model_change_snapshot,approve_model_change,execution_model,authorized_models
from forge.models import job_model
from forge.provider_errors import ProviderResourceError
from forge.tasks import TaskLedger
from forge.workspace import source_fingerprint
from test_autonomous_build import setup
from test_autonomous_testing import ready,build_checks,browsers


@pytest.fixture
def paused(ready):
    store,job,agent,boundary,review=ready;generate=agent.generate
    def limited(schema,*args,**kwargs):
        if schema.__name__=='AcceptanceSuite':raise ProviderResourceError('Provider quota')
        return generate(schema,*args,**kwargs)
    agent.generate=limited
    record=run_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    assert record['status']=='AUTONOMOUS_TEST_PAUSED'
    agent.generate=generate
    return store,job,agent,boundary,review


def test_approved_model_change_retains_plan_source_and_resumes_with_actual_provider(paused):
    store,job,agent,boundary,review=paused;before=source_fingerprint(boundary/job)
    proposal=model_change_snapshot(job,store,'qwen2.5-coder:3b',workspace_boundary=boundary)
    with pytest.raises(ValueError,match='approval'):
        approve_model_change(job,store,'qwen2.5-coder:3b',proposal['fingerprint'],workspace_boundary=boundary)
    approve_model_change(job,store,'qwen2.5-coder:3b',proposal['fingerprint'],approved=True,actor='test_user',workspace_boundary=boundary)
    assert source_fingerprint(boundary/job)==before and approved_review(job,store)['fingerprint']==review['fingerprint']
    assert job_model(store.read(job))==execution_model(job,store,review)=='qwen2.5-coder:3b'
    with pytest.raises(ValueError,match='approved job model'):
        run_tests(job,agent,store,resume=True,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    agent.model_name='qwen2.5-coder:3b'
    result=run_tests(job,agent,store,resume=True,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    assert result['status']=='AUTONOMOUS_APP_CHECKS_PASSED' and evidence_current(result,store,workspace_boundary=boundary)


@pytest.mark.parametrize('race',['source','task'])
def test_model_consent_cannot_apply_to_a_changed_checkpoint(paused,race):
    store,job,_,boundary,_=paused
    proposal=model_change_snapshot(job,store,'qwen2.5-coder:3b',workspace_boundary=boundary)
    if race=='source':(boundary/job/'app/page.tsx').write_text('Changed after review')
    else:
        ledger=TaskLedger(store,job);state=ledger.read(proposal['binding']['task_id']);ledger.revise(state,state.task)
    with pytest.raises(ValueError):
        approve_model_change(job,store,'qwen2.5-coder:3b',proposal['fingerprint'],approved=True,actor='test_user',workspace_boundary=boundary)
    assert not any(e['status']=='INFERENCE_CHANGE_APPROVED' for e in store.read(job)['events'])


def test_model_change_does_not_rewrite_a_previously_frozen_contract(ready):
    store,job,agent,boundary,review=ready;generate=agent.generate
    def limited(schema,*args,**kwargs):
        if schema.__name__=='RepairFocus':raise ProviderResourceError('Provider quota')
        return generate(schema,*args,**kwargs)
    agent.generate=limited
    record=run_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([False]))
    assert record['status']=='AUTONOMOUS_TEST_PAUSED'
    contract=next(e['payload'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_ACCEPTANCE_FROZEN')
    from pathlib import Path
    path=Path(contract['report']);original=path.read_bytes()
    proposal=model_change_snapshot(job,store,'qwen2.5-coder:3b',workspace_boundary=boundary)
    approve_model_change(job,store,'qwen2.5-coder:3b',proposal['fingerprint'],approved=True,actor='test_user',workspace_boundary=boundary)
    agent.generate=generate;agent.model_name='qwen2.5-coder:3b'
    record=run_tests(job,agent,store,resume=True,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    assert record['status']=='AUTONOMOUS_APP_CHECKS_PASSED' and path.read_bytes()==original
    assert json.loads(original)['model']=='qwen2.5-coder:7b'
    assert authorized_models(job,store,review)==['qwen2.5-coder:7b','qwen2.5-coder:3b']


def test_forged_inference_change_cannot_authorize_a_new_model(paused):
    store,job,_,_,review=paused
    store.event(job,'INFERENCE_CHANGE_APPROVED',{'model':'qwen2.5-coder:3b','actor':'unknown',
        'binding':{'review_fingerprint':review['fingerprint']}},update_status=False)
    with pytest.raises(ValueError,match='approval'):execution_model(job,store,review)
