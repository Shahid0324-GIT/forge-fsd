import json
import pytest
from pydantic import BaseModel
from forge.anthropic_model import AnthropicChat
from forge.provider_errors import ProviderResourceError

class Answer(BaseModel):
    value:int

def reply(content=None,reason='tool_use'):
    return json.dumps({'stop_reason':reason,'content':content or [{'type':'tool_use','name':'emit_result','input':{'result':{'value':3}}}],
        'usage':{'input_tokens':10,'output_tokens':5}}).encode()

def test_schema_data_is_validated_and_copies_share_paid_request_allowance(monkeypatch):
    calls=[]
    def post(self,payload):calls.append(payload);return 200,reply()
    monkeypatch.setattr(AnthropicChat,'_post',post)
    model=AnthropicChat()
    for _ in range(4):
        result=model.model_copy(update={'num_predict':1200}).with_structured_output(Answer,include_raw=True).invoke([('system','Return data'),('human','Three')])
        assert result['parsed'].value==3
    with pytest.raises(ProviderResourceError,match='4 requests'):model.with_structured_output(Answer).invoke('Three')
    assert len(calls)==4 and calls[0]['max_tokens']==1200
    assert calls[0]['tools'][0]['input_schema']['properties']['result']==Answer.model_json_schema()
    assert calls[0]['tool_choice']['disable_parallel_tool_use']
    assert calls[0]['tool_choice']['type']=='auto' and calls[0]['output_config']['effort']=='low'
    assert result['raw'].usage_metadata['total_tokens']==15

@pytest.mark.parametrize('reason',['max_tokens','refusal','pause_turn'])
def test_incomplete_source_cannot_be_written(monkeypatch,reason):
    monkeypatch.setattr(AnthropicChat,'_post',lambda *_:(200,reply([{'type':'text','text':'partial'}],reason)))
    with pytest.raises(ProviderResourceError,match='incomplete'):AnthropicChat().invoke('Source')

def test_invalid_structured_data_is_not_a_validated_proposal(monkeypatch):
    monkeypatch.setattr(AnthropicChat,'_post',lambda *_:(200,reply([{'type':'tool_use','name':'emit_result','input':{'result':{'value':'bad'}}}])))
    result=AnthropicChat().with_structured_output(Answer,include_raw=True).invoke('Three')
    assert result['parsed'] is None and result['parsing_error']

def test_response_bodies_and_credentials_never_appear_in_provider_error(monkeypatch):
    monkeypatch.setattr(AnthropicChat,'_post',lambda *_:(401,b'sensitive response body'))
    with pytest.raises(ProviderResourceError,match='Claude HTTP 401') as error:AnthropicChat().invoke('Hello')
    assert 'sensitive' not in str(error.value)

def test_source_output_ignores_thinking_blocks_and_keeps_provider_identity(monkeypatch):
    monkeypatch.setattr(AnthropicChat,'_post',lambda *_:(200,reply([{'type':'thinking','thinking':'private'}, {'type':'text','text':'export const value=3;'}],'end_turn')))
    raw=AnthropicChat().invoke('Source')
    assert raw.content=='export const value=3;' and raw.response_metadata['provider']=='anthropic'
    assert 'private' not in str(raw)


def test_root_union_is_wrapped_without_changing_business_types_or_reference_targets(monkeypatch):
    from pydantic import RootModel
    class Other(BaseModel):
        label:str
    class Choice(RootModel[Answer|Other]):pass
    original=Choice.model_json_schema();payloads=[]
    def post(self,payload):
        payloads.append(payload)
        return 200,reply([{'type':'tool_use','name':'emit_result','input':{'result':{'label':'valid'}}}])
    monkeypatch.setattr(AnthropicChat,'_post',post)
    result=AnthropicChat().with_structured_output(Choice).invoke('Choose')
    assert isinstance(result.root,Other)
    wire=payloads[0]['tools'][0]['input_schema']
    assert wire['type']=='object' and wire['$defs']==original['$defs']
    assert wire['properties']['result']['anyOf']==original['anyOf']
    assert Choice.model_json_schema()==original
