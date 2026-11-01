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


def test_design_review_sends_findings_back_before_returning_plan():
    from copy import deepcopy
    from forge.schemas import AppImplementationPlan,ArchitectureReview
    from test_general_apps import calculator_plan
    original={'original_request':'Build a tip calculator','requirements':{'title':'Calculator'}}
    untouched=deepcopy(original);calls=[];handoffs=[]
    agent=OllamaAgents.__new__(OllamaAgents)
    def generate(schema,instruction,data,**kwargs):
        calls.append((schema,deepcopy(data)))
        if schema is ArchitectureReview:
            return ArchitectureReview(issues=['Specify the API response shape.'] if len(calls)==2 else [])
        return AppImplementationPlan.model_validate(calculator_plan())
    agent.generate=generate;agent.handoff=lambda *args:handoffs.append(args)
    result=agent.reviewed_generate(AppImplementationPlan,'Architect',original,ArchitectureReview,'Review')
    assert result.database=='none'
    assert [schema for schema,_ in calls]==[AppImplementationPlan,ArchitectureReview,AppImplementationPlan,ArchitectureReview]
    assert calls[2][1]['review_findings']==['Specify the API response shape.']
    assert calls[2][1]['previous_proposal']==calls[1][1]['proposal']
    assert original==untouched
    assert [(h[0],h[1]) for h in handoffs]==[('architect_agent','architecture_reviewer'),('architecture_reviewer','architect_agent'),('architect_agent','architecture_reviewer')]


def test_unresolved_model_critique_remains_visible_and_does_not_override_valid_contract():
    from forge.schemas import NativeAcceptancePlan,AcceptanceReview
    bad=persistence_proposal();bad['scenarios'][-1]['steps'][0]['expected']=[{'title':'Keep me'}]
    agent=OllamaAgents.__new__(OllamaAgents);calls=[];events=[]
    agent.activity=lambda status,payload:events.append((status,payload))
    def generate(schema,instruction,data,**kwargs):
        calls.append(schema)
        if schema is AcceptanceReview:return AcceptanceReview(issues=['The restart fixture was deleted before restart.'])
        return NativeAcceptancePlan.model_validate(bad)
    agent.generate=generate
    result=agent.reviewed_generate(NativeAcceptancePlan,'QA',{},AcceptanceReview,'Review')
    assert result.database=='sqlite'
    assert events[-1][1]['advisory'] is True
    assert events[-1][1]['issues']==['The restart fixture was deleted before restart.']
    assert calls==[NativeAcceptancePlan,AcceptanceReview,NativeAcceptancePlan,AcceptanceReview]


def test_captured_crud_restart_fixture_must_survive_deletion():
    from pydantic import ValidationError
    from forge.schemas import NativeAcceptancePlan
    data=persistence_proposal()
    create=data['scenarios'][0]['steps'][0]
    create.update(save_as='item_id',save_pointer='/id')
    data['scenarios'][0]['steps'].append({'method':'DELETE','path':'/api/items/{{item_id}}','body':None,'status':204,'expected':None})
    data['scenarios'][-1]['steps'][0]['expected']=[{'title':'Keep me'}]
    with pytest.raises(ValidationError,match='all its captured records were deleted'):
        NativeAcceptancePlan.model_validate(data)
    from copy import deepcopy
    reused=deepcopy(data)
    reused['scenarios'][0]['steps'].insert(1,dict(reused['scenarios'][0]['steps'][0]))
    # Reusing a capture leaves the previous record untracked; do not assume it was deleted.
    assert NativeAcceptancePlan.model_validate(reused).database=='sqlite'
    data['scenarios'][0]['steps'].append({'method':'POST','path':'/api/items','body':{'title':'Keep me'},'status':201,'expected':{'title':'Keep me'},'save_as':'retained_id','save_pointer':'/id'})
    assert NativeAcceptancePlan.model_validate(data).database=='sqlite'


def test_vague_architecture_cannot_replace_a_concrete_api_contract():
    from pydantic import ValidationError
    from forge.schemas import AppImplementationPlan
    from test_general_apps import calculator_plan
    data=calculator_plan();data['tasks'][1]['contract']='Implement calculations and validation.'
    with pytest.raises(ValidationError,match='Backend contract must specify'):
        AppImplementationPlan.model_validate(data)
