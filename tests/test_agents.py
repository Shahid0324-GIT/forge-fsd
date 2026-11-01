from types import SimpleNamespace

import pytest

from forge.agents import OllamaAgents
from forge.schemas import RequirementsDocument


class FakeModel:
    def __init__(self, response):
        self.response = response

    def with_structured_output(self, schema, **kwargs):
        assert kwargs == {"method": "json_schema", "include_raw": True}
        return self

    def invoke(self, messages):
        return self.response


@pytest.mark.parametrize("reason", ["length", None])
def test_incomplete_model_response_is_rejected(reason):
    agents = OllamaAgents.__new__(OllamaAgents)
    agents.model = FakeModel({"raw": SimpleNamespace(response_metadata={"done_reason": reason}),
                              "parsed": {}, "parsing_error": None})
    with pytest.raises(ValueError, match="did not complete normally"):
        agents.generate(RequirementsDocument, "instruction", {})


def test_provider_parse_failure_is_rejected():
    agents = OllamaAgents.__new__(OllamaAgents)
    agents.model = FakeModel({"parsing_error": "invalid JSON"})
    with pytest.raises(ValueError, match="invalid JSON"):
        agents.generate(RequirementsDocument, "instruction", {})


def persistence_proposal():
    return {'database':'sqlite','scenarios':[
        {'name':'Create stored item','phase':'functional','steps':[
            {'method':'POST','path':'/api/items','body':{'title':'Keep me'},'status':201,'expected':{'title':'Keep me'}}]},
        {'name':'Reject invalid title','phase':'functional','steps':[
            {'method':'POST','path':'/api/items','body':{'title':''},'status':400,'expected':None}]},
        {'name':'Read after restart','phase':'restart','steps':[
            {'method':'GET','path':'/api/items','body':None,'status':200,'expected':[]}]},
    ]}


def test_qa_correction_receives_rejected_proposal_and_preserves_validation():
    import json
    from pydantic import ValidationError
    from forge.schemas import NativeAcceptancePlan
    bad=persistence_proposal()
    with pytest.raises(ValidationError) as invalid:
        NativeAcceptancePlan.model_validate(bad)
    corrected=json.loads(json.dumps(bad))
    corrected['scenarios'][-1]['steps'][0]['expected']=[{'title':'Keep me'}]
    messages_seen=[]
    events=[]
    class RepairModel(FakeModel):
        def invoke(self,messages):
            messages_seen.append(list(messages))
            if len(messages_seen)==1:
                return {'raw':SimpleNamespace(content=json.dumps(bad),response_metadata={'done_reason':'stop'}),
                        'parsed':None,'parsing_error':invalid.value}
            return {'raw':SimpleNamespace(response_metadata={'done_reason':'stop'}),
                    'parsed':NativeAcceptancePlan.model_validate(corrected),'parsing_error':None}
    agent=OllamaAgents.__new__(OllamaAgents)
    agent.model=RepairModel(None);agent.model_name='test'
    agent.activity=lambda status,payload:events.append((status,payload))
    result=agent.generate(NativeAcceptancePlan,'QA instruction',{'original_request':'Persist items'})
    assert result.scenarios[-1].steps[0].expected==[{'title':'Keep me'}]
    assert ('assistant',json.dumps(bad)) in messages_seen[1]
    correction=messages_seen[1][-1][1]
    assert 'asserting stored JSON data' in correction
    assert 'COMPLETE corrected JSON' in correction
    assert 'Do not remove assertions' in correction
    assert [status for status,_ in events]==['AGENT_CALL_STARTED','AGENT_VALIDATION_FAILED','AGENT_CALL_STARTED','AGENT_CALL_COMPLETED']
    assert events[1][1]['retrying'] is True
    assert all('output' not in payload for _,payload in events)


def test_qa_correction_stays_bounded_and_reports_concise_error():
    from pydantic import ValidationError
    from forge.schemas import NativeAcceptancePlan
    with pytest.raises(ValidationError) as invalid:
        NativeAcceptancePlan.model_validate(persistence_proposal())
    agent=OllamaAgents.__new__(OllamaAgents)
    agent.model=FakeModel({'raw':SimpleNamespace(content='{}',response_metadata={'done_reason':'stop'}),
                           'parsed':None,'parsing_error':invalid.value})
    events=[];agent.model_name='test';agent.activity=lambda status,payload:events.append((status,payload))
    with pytest.raises(ValueError,match='asserting stored JSON data') as failure:
        agent.generate(NativeAcceptancePlan,'QA instruction',{})
    assert len(str(failure.value))<400
    assert sum(status=='AGENT_CALL_STARTED' for status,_ in events)==2
    assert events[-1][1]['retrying'] is False
