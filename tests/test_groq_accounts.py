import json

import pytest

from forge import groq_model as provider
from forge.provider_errors import ProviderResourceError
from test_groq_model import Answer,response,isolated_provider_capacity


@pytest.fixture
def accounts(tmp_path,monkeypatch,isolated_provider_capacity):
    config=tmp_path/'.env.local';config.write_text('')
    monkeypatch.setattr(provider,'KEY_FILE',config)
    monkeypatch.setenv('GROQ_API_KEY','first-private-credential')
    monkeypatch.setenv('GROQ_API_KEY_1','second-private-credential')
    monkeypatch.setenv('FORGE_GROQ_FALLBACK_KEY_NAME','GROQ_API_KEY_1')
    return config


def transport(monkeypatch,replies):
    sent=[]
    class Reply:
        def __init__(self,status,retry,body):self.status=status;self.retry=retry;self.body=body
        def read(self,_):return self.body
        def getheader(self,name):return self.retry if name=='Retry-After' else None
    class Connection:
        def __init__(self,*_,**__):pass
        def request(self,method,path,body,headers):sent.append((headers['Authorization'],json.loads(body)))
        def getresponse(self):return Reply(*replies.pop(0))
        def close(self):pass
    monkeypatch.setattr(provider.http.client,'HTTPSConnection',Connection)
    return sent


def test_daily_limit_switches_accounts_with_identical_model_request_and_safe_provenance(accounts,monkeypatch):
    sent=transport(monkeypatch,[(429,'3600',b'private account tokens per day: Limit 200000, Used 199000, Requested 5000'),(200,None,response())])
    model=provider.GroqChat()
    result=model.with_structured_output(Answer,include_raw=True).invoke('Return value three')
    assert result['parsed'].value==3 and len(sent)==2
    assert sent[0][0]=='Bearer first-private-credential' and sent[1][0]=='Bearer second-private-credential'
    assert sent[0][1]==sent[1][1]
    route=result['raw'].response_metadata['groq_accounts']
    assert route['key_slot']=='GROQ_API_KEY_1' and route['fallback_enabled']
    assert [a['http_status'] for a in route['attempts']]==[429,200]
    public=json.dumps(result['raw'].response_metadata)+model.model_dump_json()+repr(model)
    assert 'private' not in public and 'credential' not in public


def test_exhausted_account_is_skipped_until_its_cooldown_expires(accounts,monkeypatch):
    clock=[100.0];monkeypatch.setattr(provider.time,'monotonic',lambda:clock[0])
    sent=transport(monkeypatch,[(429,'10',b'tokens per minute'),(200,None,response()),(200,None,response()),(200,None,response())])
    model=provider.GroqChat();model.invoke('First')
    second=model.invoke('Second')
    assert len(sent)==3 and second.response_metadata['groq_accounts']['attempts'][0]['outcome']=='cooldown'
    clock[0]+=11
    third=model.model_copy(update={'num_predict':1200}).invoke('Third')
    assert len(sent)==4 and third.response_metadata['groq_accounts']['key_slot']=='GROQ_API_KEY'


def test_both_accounts_limited_pause_without_sleep_repair_or_unbounded_retry(accounts,monkeypatch):
    sent=transport(monkeypatch,[(429,'2',b'tokens per minute: Limit 8000'),(429,'2',b'tokens per minute: Limit 8000')])
    monkeypatch.setattr(provider.time,'sleep',lambda *_:pytest.fail('Pool exhaustion must pause, not loop'))
    with pytest.raises(ProviderResourceError) as error:provider.GroqChat().invoke('Test')
    assert len(sent)==2 and 'GROQ_API_KEY=429' in str(error.value) and 'GROQ_API_KEY_1=429' in str(error.value)
    assert 'private' not in str(error.value)
    with pytest.raises(ProviderResourceError):provider.GroqChat().invoke('Next request')
    assert len(sent)==2  # Both cooldowns prevent another network attempt.


@pytest.mark.parametrize('status',[400,401,403,413,500])
def test_nonquota_failures_never_switch_accounts(accounts,monkeypatch,status):
    sent=transport(monkeypatch,[(status,None,b'private provider details')])
    with pytest.raises(ProviderResourceError):provider.GroqChat().invoke('Test')
    assert len(sent)==1


def test_invalid_json_stays_a_producing_agent_error_not_an_account_failure(accounts,monkeypatch):
    body=b'{"error":{"code":"json_validate_failed","failed_generation":"{\\"value\\":"}}'
    sent=transport(monkeypatch,[(400,None,body)])
    result=provider.GroqChat().with_structured_output(Answer,include_raw=True).invoke('Test')
    assert result['parsed'] is None and result['parsing_error'] and len(sent)==1
    assert result['raw'].response_metadata['groq_accounts']['key_slot']=='GROQ_API_KEY'


@pytest.mark.parametrize('fallback,value',[('GROQ_API_KEY','second-private-credential'),('OTHER_SECRET','second-private-credential'),('GROQ_API_KEY_1',''),('GROQ_API_KEY_1','first-private-credential')])
def test_invalid_pool_configuration_fails_before_network(accounts,monkeypatch,fallback,value):
    monkeypatch.setenv('FORGE_GROQ_FALLBACK_KEY_NAME',fallback);monkeypatch.setenv('GROQ_API_KEY_1',value)
    monkeypatch.setattr(provider.http.client,'HTTPSConnection',lambda *_a,**_k:pytest.fail('No network with invalid pool'))
    assert not provider.groq_configured()
    with pytest.raises(ProviderResourceError,match='configuration'):provider.GroqChat().invoke('Test')


def test_disabled_pool_preserves_explicit_selected_key(accounts,monkeypatch):
    monkeypatch.setenv('FORGE_GROQ_FALLBACK_KEY_NAME','')
    sent=transport(monkeypatch,[(429,None,b'tokens per day')])
    with pytest.raises(ProviderResourceError):provider.GroqChat().invoke('Test')
    assert len(sent)==1


def test_pool_config_works_from_file_and_environment_can_disable_it(accounts,monkeypatch):
    accounts.write_text('GROQ_API_KEY=file-first\nGROQ_API_KEY_1=file-second\nFORGE_GROQ_KEY_NAME=GROQ_API_KEY_1\nFORGE_GROQ_FALLBACK_KEY_NAME=GROQ_API_KEY\n')
    for name in ('GROQ_API_KEY','GROQ_API_KEY_1','FORGE_GROQ_KEY_NAME','FORGE_GROQ_FALLBACK_KEY_NAME'):monkeypatch.delenv(name)
    assert provider.groq_accounts()==[('GROQ_API_KEY_1','file-second'),('GROQ_API_KEY','file-first')]
    monkeypatch.setenv('FORGE_GROQ_FALLBACK_KEY_NAME','')
    assert provider.groq_accounts()==[('GROQ_API_KEY_1','file-second')]


def test_transport_failure_is_not_replayed_with_another_account(accounts,monkeypatch):
    calls=[]
    class Offline:
        def __init__(self,*_,**__):pass
        def request(self,*_,**__):calls.append(True);raise OSError('private transport details')
        def close(self):pass
    monkeypatch.setattr(provider.http.client,'HTTPSConnection',Offline)
    with pytest.raises(ProviderResourceError) as error:provider.GroqChat().invoke('Test')
    assert len(calls)==1 and 'private' not in str(error.value)


def test_account_route_is_saved_in_call_trace_and_live_activity(accounts,monkeypatch,tmp_path):
    from forge.agents import OllamaAgents
    sent=transport(monkeypatch,[(429,None,b'tokens per day'),(200,None,response())])
    agent=OllamaAgents.__new__(OllamaAgents);agent.model=provider.GroqChat();agent.model_name=provider.GROQ_MODEL
    agent.trace_directory=tmp_path/'traces';events=[];agent.activity=lambda status,payload:events.append((status,payload))
    assert agent.generate(Answer,'Return three',{}).value==3
    trace=json.loads(next(agent.trace_directory.glob('*.json')).read_text())
    assert trace['provider_metadata']['groq_accounts']['key_slot']=='GROQ_API_KEY_1'
    route=next(data for status,data in events if status=='PROVIDER_ACCOUNT_ROUTED')
    assert route['key_slot']=='GROQ_API_KEY_1' and len(sent)==2
    assert 'private' not in json.dumps(events)+json.dumps(trace)
