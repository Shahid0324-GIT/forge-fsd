import json
from concurrent.futures import ThreadPoolExecutor
import pytest

from forge.persistence import JobStore
from forge.claude_budget import RunBudget,authorize,MODEL
from forge.anthropic_model import AnthropicChat
from forge.provider_errors import ProviderResourceError
from test_api import client,session,fake_submit


@pytest.fixture
def budget(tmp_path):
    store=JobStore(tmp_path/'jobs.sqlite3');job=store.create({'model':MODEL})
    authorize(store,job,approved=True,actor='test_user')
    return store,job,RunBudget.for_job(store,job)


def test_authorization_is_required_before_budget_is_available(tmp_path):
    store=JobStore(tmp_path/'jobs.sqlite3');job=store.create({'model':MODEL})
    assert RunBudget.for_job(store,job) is None
    with pytest.raises(ValueError,match='approval'):authorize(store,job)


def test_budget_persists_and_replaces_four_call_limit_only_when_explicitly_attached(budget,monkeypatch):
    store,job,allowance=budget
    response=json.dumps({'stop_reason':'end_turn','content':[{'type':'text','text':'OK'}],
        'usage':{'input_tokens':10,'output_tokens':5}}).encode()
    monkeypatch.setattr(AnthropicChat,'_post',lambda *_:(200,response))
    model=AnthropicChat();model._run_budget=allowance
    for _ in range(6):assert model.model_copy().invoke('Test').content=='OK'
    summary=RunBudget.for_job(JobStore(store.path),job).summary()
    assert summary['requests_used']==6 and summary['charged_or_reserved_usd']==pytest.approx(0.00084)


def test_concurrent_requests_cannot_reserve_more_than_the_run_allowance(budget):
    _,_,allowance=budget;payload={'max_tokens':3000,'messages':'x'*190000}
    def reserve(_):
        try:return allowance.reserve(payload)
        except ProviderResourceError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(reserve,range(2)))
    assert sum(result is not None for result in results)==1
    assert allowance.summary()['charged_or_reserved_usd']<=3


def test_unknown_usage_keeps_reservation_and_settlement_cannot_be_replayed(budget):
    _,_,allowance=budget;identifier=allowance.reserve({'max_tokens':3000})
    before=allowance.summary()['charged_or_reserved_usd']
    with pytest.raises(ProviderResourceError):allowance.settle(identifier,{})
    assert allowance.summary()['charged_or_reserved_usd']==before
    allowance.settle(identifier,{'input_tokens':10,'output_tokens':5})
    with pytest.raises(ValueError):allowance.settle(identifier,{'input_tokens':10,'output_tokens':5})


def test_oversized_reservation_stops_before_http(budget,monkeypatch):
    _,_,allowance=budget;model=AnthropicChat();model._run_budget=allowance
    monkeypatch.setattr(AnthropicChat,'_post',lambda *_:pytest.fail('Request must not be sent'))
    with pytest.raises(ProviderResourceError,match='budget'):model.invoke('x'*400000)
    assert allowance.summary()['requests_used']==0


def test_dashboard_claude_creation_requires_explicit_budget_and_authorizes_before_submission(client,monkeypatch):
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    monkeypatch.setattr('forge.anthropic_model.anthropic_key',lambda:'test-key')
    from uuid import uuid4
    body={'description':'Build a small interactive calculator','model':MODEL,'workflow':'autonomous','request_id':uuid4().hex}
    assert browser.post('/api/jobs',headers=headers,json=body).status_code==422
    assert not app.state.store.list_jobs()
    created=browser.post('/api/jobs',headers=headers,json={**body,'claude_budget_usd':3})
    assert created.status_code==202 and len(calls)==1
    job=created.json()['job_id'];assert RunBudget.for_job(app.state.store,job).summary()['requests_used']==0
    view=browser.get('/api/jobs/'+job).json();assert view['provider_budget']['run_budget_usd']==3
