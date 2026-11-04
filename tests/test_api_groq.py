from uuid import uuid4
import pytest

from forge.groq_model import GROQ_MODEL,GROQ_MODELS
from forge.models import job_model
from forge.models import HYBRID_MODEL
from test_api import client,session,fake_submit


@pytest.mark.parametrize('model',sorted(GROQ_MODELS|{HYBRID_MODEL}))
def test_hosted_model_requires_local_configuration_and_autonomous_workflow(client,monkeypatch,model):
    import forge.api as api
    browser,app=client;headers=session(browser);calls=fake_submit(app,monkeypatch)
    monkeypatch.setattr(api,'groq_configured',lambda:False)
    body={'description':'Build a small saved notes application','model':model,'workflow':'autonomous','request_id':uuid4().hex}
    assert browser.post('/api/jobs',headers=headers,json=body).status_code==422
    assert not calls and app.state.store.list_jobs()==[]
    monkeypatch.setattr(api,'groq_configured',lambda:True)
    assert browser.post('/api/jobs',headers=headers,json={**body,'workflow':'typed'}).status_code==422
    response=browser.post('/api/jobs',headers=headers,json=body)
    assert response.status_code==202
    saved=app.state.store.read(response.json()['job_id'])
    assert job_model(saved)==model and calls[0][2]['model']==model


def test_session_discloses_provider_availability_without_credentials(client,monkeypatch):
    import forge.api as api
    browser,_=client;monkeypatch.setattr(api,'groq_configured',lambda:True)
    data=browser.get('/api/session').json()
    assert data['groq_configured'] is True and data['model']=='qwen2.5-coder:3b'
    assert set(data)=={'csrf','model','mode','supported_app','groq_configured','claude_configured'}


def test_unknown_or_unconfigured_model_identity_never_silently_becomes_hosted():
    assert job_model({'events':[{'status':'RECEIVED','payload':{}}]})=='qwen2.5-coder:3b'
    assert job_model({'events':[{'status':'RECEIVED','payload':{'model':'qwen2.5-coder:7b'}}]})=='qwen2.5-coder:7b'
    assert job_model({'events':[{'status':'RECEIVED','payload':{'model':'untrusted:model'}}]})=='qwen2.5-coder:3b'
