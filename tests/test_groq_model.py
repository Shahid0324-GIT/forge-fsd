import json

import pytest
from pydantic import BaseModel

from forge.agents import OllamaAgents
from forge import groq_model as provider


def response(content='{"value":3}',finish='stop'):
    return json.dumps({'id':'test-request','choices':[{'message':{'content':content,'reasoning':'must not be exposed'},'finish_reason':finish}],
        'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}).encode()


class Answer(BaseModel):value:int


@pytest.mark.parametrize('model',sorted(provider.GROQ_MODELS))
def test_provider_choice_does_not_initialize_ollama_or_change_local_defaults(monkeypatch,model):
    import forge.agents as module
    monkeypatch.setattr(provider,'groq_key',lambda:'test-key')
    monkeypatch.setattr(module,'init_chat_model',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Unexpected Ollama initialization')))
    agent=OllamaAgents(model)
    assert isinstance(agent.model,provider.GroqChat) and agent.model_name==model
    assert agent.model.model_name==model.removeprefix('groq:')


def test_credentials_are_local_ignored_configuration_not_model_state(tmp_path,monkeypatch):
    file=tmp_path/'.env.local';file.write_text('GROQ_API_KEY="local-test-key"\n')
    monkeypatch.setattr(provider,'KEY_FILE',file);monkeypatch.delenv('GROQ_API_KEY',raising=False)
    assert provider.groq_configured() and provider.groq_key()=='local-test-key'
    model=provider.GroqChat();assert 'local-test-key' not in repr(model) and 'local-test-key' not in model.model_dump_json()
    monkeypatch.setenv('GROQ_API_KEY','environment-test-key');assert provider.groq_key()=='environment-test-key'
    file.write_text('GROQ_API_KEY=your_key_here');monkeypatch.delenv('GROQ_API_KEY');assert not provider.groq_configured()


def test_structured_output_uses_provider_schema_and_still_validates_locally(monkeypatch):
    payloads=[]
    def post(self,payload):payloads.append(payload);return 200,None,response()
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    result=provider.GroqChat().with_structured_output(Answer,include_raw=True).invoke([('human','Return a value')])
    assert result['parsed'].value==3 and result['parsing_error'] is None
    assert payloads[0]['response_format']['json_schema']['strict'] is False
    assert payloads[0]['include_reasoning'] is False and 'tools' not in payloads[0]
    assert 'must not be exposed' not in str(result['raw'])
    assert result['raw'].usage_metadata['total_tokens']==30


def test_agent_keeps_native_schema_without_duplicating_it_in_hosted_prompt(tmp_path,monkeypatch):
    payloads=[]
    def post(self,payload):payloads.append(payload);return 200,None,response()
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    agent=OllamaAgents.__new__(OllamaAgents);agent.model=provider.GroqChat(model_name='openai/gpt-oss-20b');agent.model_name='groq:openai/gpt-oss-20b';agent.trace_directory=tmp_path
    result=agent.generate(Answer,'Return value 3',{})
    assert result.value==3
    assert payloads[0]['response_format']['json_schema']['schema']==Answer.model_json_schema()
    assert '"properties"' not in payloads[0]['messages'][0]['content']


def test_small_repair_metadata_uses_a_bounded_budget_without_changing_schema(tmp_path,monkeypatch):
    from pydantic import create_model
    schema=create_model('RepairFocus',__base__=Answer);payloads=[]
    def post(self,payload):payloads.append(payload);return 200,None,response()
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    agent=OllamaAgents.__new__(OllamaAgents);agent.model=provider.GroqChat();agent.model_name=provider.GROQ_MODEL;agent.trace_directory=tmp_path
    assert agent.generate(schema,'Return value 3',{},coding=True).value==3
    assert payloads[0]['max_completion_tokens']==1200 and payloads[0]['reasoning_effort']=='low'
    trace=json.loads(next(tmp_path.glob('*.json')).read_text());assert trace['requested_options']['max_completion_tokens']==1200


@pytest.mark.parametrize('body',['{"value":"bad"}',json.dumps(Answer.model_json_schema())])
def test_invalid_schema_response_is_not_a_validated_proposal(monkeypatch,body):
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(200,None,response(body)))
    result=provider.GroqChat().with_structured_output(Answer,include_raw=True).invoke([('human','Return a value')])
    assert result['parsed'] is None and result['parsing_error']


def test_source_adapter_preserves_provider_identity_and_truncation_gate(tmp_path,monkeypatch):
    payloads=[]
    def post(self,payload):payloads.append(payload);return 200,None,response('export const value=3;')
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    agent=OllamaAgents.__new__(OllamaAgents);agent.model=provider.GroqChat();agent.model_name=provider.GROQ_MODEL;agent.trace_directory=tmp_path
    assert agent.generate_source('Return source',{})=='export const value=3;\n'
    assert payloads[0]['max_completion_tokens']==3000 and 'response_format' not in payloads[0]
    assert payloads[0]['reasoning_effort']=='low'
    trace=json.loads(next(tmp_path.glob('*.json')).read_text());assert trace['model']==provider.GROQ_MODEL and trace['provider_metadata']['provider']=='groq'
    assert trace['requested_options']['max_completion_tokens']==3000 and 'num_ctx' not in trace['requested_options']
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(200,None,response('partial','length')))
    from forge.provider_errors import ProviderResourceError
    with pytest.raises(ProviderResourceError,match='did not complete normally'):agent.generate_source('Return source',{})


@pytest.mark.parametrize('status',[302,400,401,429,500])
def test_provider_errors_do_not_echo_response_bodies_or_credentials(monkeypatch,status):
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(status,None,b'private-test-secret'))
    with pytest.raises(RuntimeError) as error:provider.GroqChat().invoke([('human','Test')])
    assert str(status) in str(error.value) and 'private-test-secret' not in str(error.value)


def test_one_bounded_rate_wait_preserves_the_request(monkeypatch):
    calls=[];waits=[]
    def post(self,payload):
        calls.append(payload);return (429,'2',b'') if len(calls)==1 else (200,None,response())
    monkeypatch.setattr(provider.GroqChat,'_post',post);monkeypatch.setattr(provider.time,'sleep',waits.append)
    provider.GroqChat().invoke([('human','Test')]);assert waits==[2] and calls[0]==calls[1]


def test_request_limit_reports_only_numeric_capacity_not_provider_body(monkeypatch):
    from forge.provider_errors import ProviderResourceError
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(413,None,b'private-account Limit 6000, Requested 7400 private-test-secret'))
    with pytest.raises(ProviderResourceError) as error:provider.GroqChat().invoke([('human','Test')])
    assert '6000' in str(error.value) and '7400' in str(error.value)
    assert 'private' not in str(error.value)


def test_https_destination_is_fixed_and_headers_never_become_model_input(monkeypatch):
    calls=[];monkeypatch.setenv('GROQ_API_KEY','private-test-secret')
    class Reply:
        status=200
        def read(self,limit):return response()
        def getheader(self,name):return None
    class Connection:
        def __init__(self,host,**kwargs):calls.append(host)
        def request(self,method,path,body,headers):calls.append((method,path,json.loads(body),headers))
        def getresponse(self):return Reply()
        def close(self):calls.append('closed')
    monkeypatch.setattr(provider.http.client,'HTTPSConnection',Connection)
    provider.GroqChat().invoke([('human','Test')])
    assert calls[0]=='api.groq.com' and calls[-1]=='closed'
    assert calls[1][3]['Authorization']=='Bearer private-test-secret'
    assert 'private-test-secret' not in json.dumps(calls[1][2])
