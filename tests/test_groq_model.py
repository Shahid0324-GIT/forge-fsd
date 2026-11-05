import json

import pytest
from pydantic import BaseModel

from forge.agents import OllamaAgents
from forge import groq_model as provider
from forge.schema_wire import compact_titles


def response(content='{"value":3}',finish='stop'):
    return json.dumps({'id':'test-request','choices':[{'message':{'content':content,'reasoning':'must not be exposed'},'finish_reason':finish}],
        'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}).encode()


class Answer(BaseModel):value:int


@pytest.fixture(autouse=True)
def isolated_provider_capacity(monkeypatch):
    monkeypatch.setattr(provider,'_TOKEN_BUDGETS',{})
    monkeypatch.setenv('FORGE_GROQ_KEY_NAME','GROQ_API_KEY')
    monkeypatch.setenv('GROQ_API_KEY','unit-test-placeholder')


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


def test_numbered_key_selection_is_explicit_persistent_and_never_falls_back(tmp_path,monkeypatch):
    file=tmp_path/'.env.local'
    file.write_text('GROQ_API_KEY=primary-test\nGROQ_API_KEY_1=alternate-test\nFORGE_GROQ_KEY_NAME=GROQ_API_KEY_1\n')
    monkeypatch.setattr(provider,'KEY_FILE',file)
    monkeypatch.delenv('FORGE_GROQ_KEY_NAME');monkeypatch.delenv('GROQ_API_KEY')
    monkeypatch.delenv('GROQ_API_KEY_1',raising=False)
    assert provider.groq_key_name()=='GROQ_API_KEY_1' and provider.groq_key()=='alternate-test'
    monkeypatch.setenv('GROQ_API_KEY_1','environment-alternate')
    assert provider.groq_key()=='environment-alternate'
    monkeypatch.setenv('FORGE_GROQ_KEY_NAME','GROQ_API_KEY_2')
    with pytest.raises(ValueError,match='no other key'):provider.groq_key()
    assert not provider.groq_configured()
    monkeypatch.setenv('FORGE_GROQ_KEY_NAME','OTHER_SECRET')
    with pytest.raises(ValueError,match='must select'):provider.groq_key()


def test_capacity_receipt_is_not_reused_after_explicit_credential_change(monkeypatch):
    calls=[];waits=[]
    monkeypatch.setattr(provider.time,'monotonic',lambda:0)
    monkeypatch.setattr(provider.time,'sleep',waits.append)
    old=provider.groq_key()
    provider._TOKEN_BUDGETS[provider._capacity_scope('openai/gpt-oss-120b',old)]=(0,8000,61)
    monkeypatch.setenv('GROQ_API_KEY','different-unit-test-key')
    class Reply:
        status=200
        def read(self,_):return response()
        def getheader(self,_):return None
    class Connection:
        def __init__(self,*_,**__):pass
        def request(self,*_,**kwargs):calls.append(kwargs['headers']['Authorization'])
        def getresponse(self):return Reply()
        def close(self):pass
    monkeypatch.setattr(provider.http.client,'HTTPSConnection',Connection)
    assert provider.GroqChat()._post({})[0]==200
    assert calls==['Bearer different-unit-test-key'] and not waits


def test_structured_output_uses_provider_schema_and_still_validates_locally(monkeypatch):
    payloads=[]
    def post(self,payload):payloads.append(payload);return 200,None,response()
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    result=provider.GroqChat().with_structured_output(Answer,include_raw=True).invoke([('human','Return a value')])
    assert result['parsed'].value==3 and result['parsing_error'] is None
    assert payloads[0]['response_format']=={'type':'json_object'}
    assert result['raw'].response_metadata['response_format']=='json_object_local_validation'
    assert json.loads(payloads[0]['messages'][-1]['content'].split('JSON Schema: ',1)[1])==compact_titles(Answer.model_json_schema())
    assert payloads[0]['include_reasoning'] is False and 'tools' not in payloads[0]
    assert 'must not be exposed' not in str(result['raw'])
    assert result['raw'].usage_metadata['total_tokens']==30


def test_agent_preserves_exact_schema_once_in_json_object_transport(tmp_path,monkeypatch):
    payloads=[]
    def post(self,payload):payloads.append(payload);return 200,None,response()
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    agent=OllamaAgents.__new__(OllamaAgents);agent.model=provider.GroqChat(model_name='openai/gpt-oss-20b');agent.model_name='groq:openai/gpt-oss-20b';agent.trace_directory=tmp_path
    result=agent.generate(Answer,'Return value 3',{})
    assert result.value==3
    assert payloads[0]['response_format']=={'type':'json_object'}
    assert sum('JSON Schema: ' in m['content'] for m in payloads[0]['messages'])==1
    assert json.loads(payloads[0]['messages'][-1]['content'].split('JSON Schema: ',1)[1])==compact_titles(Answer.model_json_schema())
    assert '"properties"' not in payloads[0]['messages'][0]['content']


@pytest.mark.parametrize('schema_name',['RepairFocus','SourceTarget','CycleRepairActions','RecoveryDecision'])
def test_small_repair_metadata_uses_a_bounded_budget_without_changing_schema(tmp_path,monkeypatch,schema_name):
    from pydantic import create_model
    schema=create_model(schema_name,__base__=Answer);payloads=[]
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
    assert payloads[0]['max_completion_tokens']==6000 and 'response_format' not in payloads[0]
    assert payloads[0]['reasoning_effort']=='low'
    trace=json.loads(next(tmp_path.glob('*.json')).read_text());assert trace['model']==provider.GROQ_MODEL and trace['provider_metadata']['provider']=='groq'
    assert trace['requested_options']['max_completion_tokens']==6000 and 'num_ctx' not in trace['requested_options']
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(200,None,response('partial','length')))
    from forge.provider_errors import ProviderResourceError
    with pytest.raises(ProviderResourceError,match='did not complete normally'):agent.generate_source('Return source',{})


@pytest.mark.parametrize('status',[302,400,401,429,500])
def test_provider_errors_do_not_echo_response_bodies_or_credentials(monkeypatch,status):
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(status,None,b'private-test-secret'))
    with pytest.raises(RuntimeError) as error:provider.GroqChat().invoke([('human','Test')])
    assert str(status) in str(error.value) and 'private-test-secret' not in str(error.value)


def test_invalid_provider_output_pauses_before_any_app_repair_and_keeps_safe_category(monkeypatch):
    from forge.provider_errors import ProviderResourceError
    body=json.dumps({'error':{'code':'json_validate_failed',
        'message':'private-test-secret: response_format contains echoed generated source',
        'failed_generation':'private source and credentials'}}).encode()
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(400,None,body))
    with pytest.raises(ProviderResourceError) as failure:provider.GroqChat().invoke('Test')
    assert 'generated JSON failed provider validation' in str(failure.value)
    assert 'request field response_format' in str(failure.value)
    assert 'private' not in str(failure.value) and 'credentials' not in str(failure.value)


@pytest.mark.parametrize('candidate',['{"value":3}','{"value":','not a JSON candidate','{"value":"gsk_'+('x'*24)+'"}'])
def test_provider_rejected_json_is_never_accepted_or_promoted_from_error_prose(monkeypatch,candidate):
    body=json.dumps({'error':{'code':'json_validate_failed','failed_generation':candidate,'message':'private account and transport details'}}).encode()
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(400,None,body))
    result=provider.GroqChat().with_structured_output(Answer,include_raw=True).invoke('Return value 3')
    assert result['parsed'] is None and result['parsing_error']
    assert result['raw'].response_metadata['json_output_rejected'] is True
    assert 'private account' not in str(result)
    assert 'gsk_' not in result['raw'].content


def test_rejected_json_gets_one_same_role_correction_with_the_unchanged_schema(tmp_path,monkeypatch):
    calls=[]
    def post(self,payload):
        calls.append(payload)
        if len(calls)==1:return 400,None,json.dumps({'error':{'code':'json_validate_failed',
            'failed_generation':'{"value":','message':'private account details'}}).encode()
        return 200,None,response('{"value":7}')
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    agent=OllamaAgents.__new__(OllamaAgents);agent.model_name=provider.GROQ_MODEL
    agent.model=provider.GroqChat();agent.trace_directory=tmp_path
    answer=agent.generate(Answer,'Return value seven.',{'original_request':'Preserve the requested calculation'})
    assert answer.value==7 and len(calls)==2
    assert calls[0]['response_format']==calls[1]['response_format']
    assert calls[0]['messages'][0]==calls[1]['messages'][0]
    assert any(message['role']=='assistant' and message['content']=='{"value":' for message in calls[1]['messages'])
    assert 'COMPLETE corrected JSON' in calls[1]['messages'][-2]['content']
    assert 'private account details' not in json.dumps(calls)
    traces=[json.loads(path.read_text()) for path in tmp_path.glob('*.json')]
    assert any(trace['outcome']=='ERROR' and trace['provider_metadata'].get('http_status')==400 for trace in traces)


def test_repeated_provider_json_rejection_stops_after_one_correction(monkeypatch):
    calls=[]
    def post(self,payload):
        calls.append(payload);return 400,None,b'{"error":{"code":"json_validate_failed"}}'
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    agent=OllamaAgents.__new__(OllamaAgents);agent.model_name=provider.GROQ_MODEL;agent.model=provider.GroqChat()
    with pytest.raises(ValueError,match='Invalid Answer output'):agent.generate(Answer,'Return value',{})
    assert len(calls)==2


def test_bad_provider_envelope_is_not_a_generated_application_defect(monkeypatch):
    from forge.provider_errors import ProviderResourceError
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(200,None,b'{"unexpected":"private transport data"}'))
    with pytest.raises(ProviderResourceError,match='invalid chat envelope') as failure:provider.GroqChat().invoke('Test')
    assert 'private transport data' not in str(failure.value)


def test_raw_chat_call_cannot_receive_a_rejected_candidate_as_a_completion(monkeypatch):
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(400,None,b'{"error":{"code":"json_validate_failed","failed_generation":"{\\"value\\":3}"}}'))
    with pytest.raises(provider.GeneratedJSONError):
        provider.GroqChat().invoke('Return value',response_schema=Answer.model_json_schema(),schema_name='Answer')


def test_unknown_provider_error_does_not_echo_arbitrary_error_codes(monkeypatch):
    from forge.provider_errors import ProviderResourceError
    body=json.dumps({'error':{'code':'private-test-secret','message':'private account details'}}).encode()
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(400,None,body))
    with pytest.raises(ProviderResourceError) as failure:provider.GroqChat().invoke('Test')
    assert '400' in str(failure.value) and 'private' not in str(failure.value)


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


def test_request_cap_fits_only_output_reserve_and_preserves_complete_input(monkeypatch):
    payloads=[]
    def post(self,payload):
        payloads.append(payload)
        return (413,None,b'Limit 8000, Requested 8216') if len(payloads)==1 else (200,None,response())
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    model=provider.GroqChat(num_predict=3000)
    result=model.with_structured_output(Answer,include_raw=True).invoke([('human','Complete original requirements')])
    assert result['parsed'].value==3 and len(payloads)==2
    assert payloads[0]['max_completion_tokens']==3000 and payloads[1]['max_completion_tokens']==2720
    assert payloads[0]['messages']==payloads[1]['messages'] and payloads[0]['response_format']==payloads[1]['response_format']
    assert result['raw'].response_metadata['max_completion_tokens']==2720
    assert result['raw'].response_metadata['completion_budget_adjusted'] is True


def test_request_cap_does_not_repeatedly_shrink_or_retry_an_unfittable_input(monkeypatch):
    from forge.provider_errors import ProviderResourceError
    calls=[]
    def post(self,payload):calls.append(payload);return 413,None,b'Limit 8000, Requested 12000'
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    with pytest.raises(ProviderResourceError):provider.GroqChat(num_predict=3000).invoke([('human','Oversized input')])
    assert len(calls)==1


@pytest.mark.parametrize('dimension',['tokens per minute','tokens per day','requests per day'])
def test_rate_limit_reports_safe_dimension_and_numeric_capacity(monkeypatch,dimension):
    from forge.provider_errors import ProviderResourceError
    body=f'private-organization {dimension}: Limit 200000, Used 199000, Requested 5000. private-key'.encode()
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(429,None,body))
    with pytest.raises(ProviderResourceError) as error:provider.GroqChat().invoke([('human','Test')])
    assert dimension in str(error.value) and 'requested 5000' in str(error.value)
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


def test_success_receipt_paces_large_calls_across_model_copies(monkeypatch):
    waits=[];clock=[10.0];calls=[]
    monkeypatch.setenv('GROQ_API_KEY','test-key')
    monkeypatch.setattr(provider.time,'monotonic',lambda:clock[0])
    def sleep(delay):waits.append(delay);clock[0]+=delay
    monkeypatch.setattr(provider.time,'sleep',sleep)
    class Reply:
        status=200
        def read(self,_):return response()
        def getheader(self,name):return {'x-ratelimit-remaining-tokens':'2000','x-ratelimit-limit-tokens':'8000','x-ratelimit-reset-tokens':'35.5s'}.get(name)
    class Connection:
        def __init__(self,*_,**__):pass
        def request(self,*_,**__):calls.append(clock[0])
        def getresponse(self):return Reply()
        def close(self):pass
    monkeypatch.setattr(provider.http.client,'HTTPSConnection',Connection)
    model=provider.GroqChat(num_predict=1200);payload={'messages':[{'content':'source'*1000}]}
    model._post(payload);model.model_copy(update={'num_predict':3000})._post(payload)
    assert waits==[35.5] and calls==[10.0,45.5]
    # A separate model's quota is independent; this model's tiny request fits.
    model._post({'messages':[]})
    model.model_copy(update={'model_name':'openai/gpt-oss-20b'})._post(payload)
    assert waits==[35.5]


@pytest.mark.parametrize('duration,expected',[('2m59.56s',179.56),('7.66s',7.66),('1h2m3s',3723),('private text',None),('nan',None)])
def test_capacity_duration_parser_accepts_only_numeric_units(duration,expected):
    assert provider._duration(duration)==expected


def test_long_capacity_wait_pauses_before_sending_another_request(monkeypatch):
    from forge.provider_errors import ProviderResourceError
    monkeypatch.setattr(provider.time,'monotonic',lambda:0)
    provider._TOKEN_BUDGETS[provider._capacity_scope('openai/gpt-oss-120b',provider.groq_key())]=(0,8000,61)
    monkeypatch.setattr(provider.http.client,'HTTPSConnection',lambda *_a,**_k:pytest.fail('Must not send'))
    with pytest.raises(ProviderResourceError,match='bounded wait'):provider.GroqChat()._post({})


def test_closed_repair_schema_uses_constrained_decoding_and_keeps_local_validation(monkeypatch):
    from forge.source_agent import RepairFocus
    payloads=[]
    def post(self,payload):
        payloads.append(payload)
        # Even a provider claiming strict decoding cannot bypass local validation.
        return 200,None,response('{"file":"app/page.tsx","cause":"Compiler error"}')
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    result=provider.GroqChat(model_name='openai/gpt-oss-20b').with_structured_output(RepairFocus,include_raw=True).invoke([('human','Diagnose')])
    assert payloads[0]['response_format']['json_schema']['strict'] is True
    assert payloads[0]['response_format']['json_schema']['schema']==compact_titles(RepairFocus.model_json_schema())
    assert result['parsed'] is None and result['parsing_error']
    assert result['raw'].response_metadata['response_format']=='json_schema_strict'


def test_optional_and_open_nested_shapes_are_not_silently_rewritten_for_strict_mode():
    from pydantic import ConfigDict
    class OptionalField(BaseModel):
        model_config=ConfigDict(extra='forbid')
        value:int=3
    class OpenChild(BaseModel):
        model_config=ConfigDict(extra='forbid')
        data:dict[str,int]
    for schema in [OptionalField,OpenChild]:
        assert not provider._strict_compatible(schema.model_json_schema())
    assert not provider._strict_compatible({'anyOf':[{'type':'string'},{'type':'integer'}]})


def test_daily_limit_never_retries_even_with_short_retry_after(monkeypatch):
    from forge.provider_errors import ProviderResourceError
    calls=[];waits=[]
    def post(self,payload):
        calls.append(payload)
        return 429,'2',b'tokens per day: Limit 200000, Used 195827, Requested 5453'
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    monkeypatch.setattr(provider.time,'sleep',waits.append)
    with pytest.raises(ProviderResourceError,match='tokens per day'):provider.GroqChat().invoke('Test')
    assert len(calls)==1 and not waits


def test_json_object_preserves_optional_defaults_and_rejects_invalid_values(monkeypatch):
    from pydantic import ConfigDict
    class OptionalAnswer(BaseModel):
        model_config=ConfigDict(extra='forbid')
        value:int=3
    original=OptionalAnswer.model_json_schema();payloads=[]
    def post(self,payload):payloads.append(payload);return 200,None,response('{}')
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    result=provider.GroqChat().with_structured_output(OptionalAnswer,include_raw=True).invoke('Test')
    assert result['parsed'].value==3
    assert json.loads(payloads[0]['messages'][-1]['content'].split('JSON Schema: ',1)[1])==compact_titles(original)
    assert OptionalAnswer.model_json_schema()==original
    monkeypatch.setattr(provider.GroqChat,'_post',lambda *_:(200,None,response('{"value":"wrong","unexpected":true}')))
    rejected=provider.GroqChat().with_structured_output(OptionalAnswer,include_raw=True).invoke('Test')
    assert rejected['parsed'] is None and rejected['parsing_error']


def test_object_root_detection_resolves_unions_without_rewriting_nonobject_roots():
    from pydantic import RootModel
    class First(BaseModel):first:str
    class Second(BaseModel):second:int
    class ObjectChoice(RootModel[First|Second]):pass
    class ArrayChoice(RootModel[list[int]]):pass
    assert provider._object_root(ObjectChoice.model_json_schema())
    assert not provider._object_root(ArrayChoice.model_json_schema())
    assert not provider._object_root({'$ref':'#/$defs/loop','$defs':{'loop':{'$ref':'#/$defs/loop'}}})


def test_actual_qa_schema_uses_local_validation_in_one_request(monkeypatch):
    from forge.autonomous_acceptance import AcceptanceSuite
    payloads=[]
    def post(self,payload):
        payloads.append(payload)
        return 200,None,response('{"scenarios":[],"uncovered":[]}')
    monkeypatch.setattr(provider.GroqChat,'_post',post)
    result=provider.GroqChat(model_name='openai/gpt-oss-20b').with_structured_output(AcceptanceSuite,include_raw=True).invoke('Test')
    assert result['parsed'] is not None and len(payloads)==1
    assert payloads[0]['response_format']=={'type':'json_object'}
    # Structural parsing is not acceptance coverage, execution, or app success.
    from forge.autonomous_acceptance import validate_coverage
    with pytest.raises(ValueError):validate_coverage(result['parsed'],3)
