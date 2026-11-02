import copy
import hashlib
import json
from types import SimpleNamespace
from pathlib import Path

import pytest
from pydantic import ValidationError

from forge.contracts import (BusinessBrief,ApiDesign,LayoutDesign,AppDesign,brief_fingerprint,
                             compile_design,render_types,validate_api)
from forge.acceptance_design import AcceptanceDesign,ParameterCapture,compile_acceptance
from forge.operations_design import ApiProposal,compile_operations,proposal_schema
from forge.layout_design import LayoutProposal,compile_layout
from forge.schemas import RequirementsDocument,validate_app_contract


def brief_fixture(persistent=True):
    return BusinessBrief(title='Record notebook' if persistent else 'Arithmetic tool',
        acceptance_criteria=['Create or calculate','Read results','Validate inputs','Keep stored data' if persistent else 'Display totals'],
        assumptions=['Single user'],open_questions=[],database='sqlite' if persistent else 'none',pages=['/'],
        data_contract={'entities':[{'name':'entry','fields':[
            {'name':'title','kind':'text','required':True,'unique':False,'min_length':1,'max_length':100},
            {'name':'amount','kind':'number','required':True,'unique':False,'lower':{'value':0,'inclusive':False}},
            {'name':'category','kind':'enum','required':True,'unique':False,'choices':['A','B']}]}] if persistent else [],'computed_outputs':[]}).to_brief()


def design_fixture(persistent=True):
    brief=brief_fixture(persistent)
    api=ApiDesign.model_validate({'records':[] if persistent else [
        {'name':'CalculationInput','fields':[{'name':'value','type':'number'}]},
        {'name':'CalculationResult','fields':[{'name':'total','type':'number'}]}],
        'endpoints':[
            {'id':'create','method':'POST','segments':[{'name':'entries' if persistent else 'calculate','parameter':False}],
             'input_type':'EntryInput' if persistent else 'CalculationInput','output_type':'Entry' if persistent else 'CalculationResult',
             'success_status':201 if persistent else 200,'error_statuses':[400],'behavior':'Save a validated entry' if persistent else 'Multiply value by two','requirement_ids':['R1','R3']},
            *([{'id':'list','method':'GET','segments':[{'name':'entries','parameter':False}],'input_type':'none','output_type':'Entry[]',
               'success_status':200,'behavior':'Return persisted entries','requirement_ids':['R2','R4']},
              {'id':'update','method':'PATCH','segments':[{'name':'entries','parameter':False},{'parameter':True}],
               'input_type':'EntryPatch','output_type':'Entry','success_status':200,'error_statuses':[400,404],
               'behavior':'Update an existing entry','requirement_ids':['R1']},
              {'id':'delete','method':'DELETE','segments':[{'name':'entries','parameter':False},{'parameter':True}],
               'input_type':'none','output_type':'none','success_status':204,'error_statuses':[404],
               'behavior':'Delete an existing entry','requirement_ids':['R1']}] if persistent else [])]})
    layout=LayoutDesign(pages=[{'path':'/','endpoint_ids':[e.id for e in api.endpoints],
        'behavior':'Use labeled inputs and refresh results after mutations','requirement_ids':['R1','R2','R3','R4']}])
    return brief,AppDesign(brief_fingerprint=brief_fingerprint(brief),api=api,layout=layout)


def acceptance_fixture():
    fields={'title':'Stored','amount':10,'category':'A'}
    return AcceptanceDesign(scenarios=[
        {'name':'Create','phase':'functional','requirement_ids':['R1'],'steps':[
            {'operation_id':'create','body':fields,'expected':fields,'status':201,'save_as':'entry_id','save_pointer':'/id'}]},
        {'name':'Invalid','phase':'functional','requirement_ids':['R3'],'steps':[
            {'operation_id':'create','body':{'title':'','amount':0,'category':'A'},'expected':None,'status':400}]},
        {'name':'Restart','phase':'restart','requirement_ids':['R4'],'steps':[
            {'operation_id':'list','body':None,'expected':[fields],'status':200}]}])


def test_compiler_derives_routes_files_and_interfaces_once():
    brief,design=design_fixture()
    plan=compile_design(brief,design)
    assert plan.routes==['POST /api/entries','GET /api/entries','PATCH /api/entries/{id}','DELETE /api/entries/{id}']
    assert plan.tasks[1].files==['app/api/entries/route.ts','app/api/entries/[id]/route.ts']
    req=RequirementsDocument.model_validate({**brief.model_dump(),'scenarios':compile_acceptance(brief,design,acceptance_fixture()).model_dump()['scenarios']})
    validate_app_contract(req,plan)
    changed=plan.model_copy(deep=True);changed.tasks[1].files.pop()
    with pytest.raises(ValueError,match='authoritative typed design'):validate_app_contract(req,changed)
    changed=plan.model_copy(deep=True);changed.routes[0]='POST /api/something'
    with pytest.raises(ValueError,match='authoritative typed design'):validate_app_contract(req,changed)
    assert 'export interface EntryInput' in render_types(brief,design)
    assert 'id: number;' in render_types(brief,design)


@pytest.mark.parametrize('persistent',[True,False])
def test_same_compiler_handles_persistent_and_stateless_decisions(persistent):
    brief,design=design_fixture(persistent)
    plan=compile_design(brief,design)
    assert plan.database==brief.database
    assert plan.design==design
    assert plan.tasks[0].files==['app/page.tsx']
    changed=brief.model_copy(update={'title':'A different business request'})
    with pytest.raises(ValueError,match='different business brief'):compile_design(changed,design)


def test_entity_references_and_enum_rules_are_explicit():
    data=BusinessBrief.model_validate({**brief_fixture().model_dump(exclude={'spec_version','entities'}),
                                      'data_contract':brief_fixture().data_contract.model_dump()}).model_dump()
    data['data_contract']['entities'][0]['fields'][2]['choices']=[]
    with pytest.raises(ValidationError,match='choices'):BusinessBrief.model_validate(data)
    data['data_contract']['entities'][0]['fields'][2].pop('choices')
    data['data_contract']['entities'][0]['fields'][2].update(kind='reference',reference='missing')
    with pytest.raises(ValidationError,match='unknown reference'):BusinessBrief.model_validate(data)
    data['data_contract']['entities'].append({'name':'group','fields':[{'name':'label','kind':'text','required':True,'unique':False}]})
    data['data_contract']['entities'][0]['fields'][2]['reference']='group'
    assert BusinessBrief.model_validate(data).root.data_contract.entities[0].fields[2].reference=='group'


def test_model_visible_schema_encodes_type_and_storage_alternatives():
    schema=BusinessBrief.model_json_schema()
    assert schema['discriminator']['propertyName']=='database'
    definitions=schema['$defs']
    assert 'min_length' not in definitions['NumberField']['properties']
    assert 'lower' in definitions['NumberField']['properties']
    assert 'choices' in definitions['EnumField']['required']
    assert definitions['StatelessData']['properties']['entities']['maxItems']==0
    assert definitions['StoredData']['properties']['entities']['minItems']==1
    assert 'records' in ApiProposal.model_json_schema()['required']


def test_later_roles_cannot_invent_symbols_or_framework_parameter_labels():
    from forge.layout_design import layout_proposal_schema
    from forge.acceptance_design import acceptance_schema
    brief,design=design_fixture()
    layout=design.layout.model_dump()
    layout.pop('components');layout['pages'][0]['components']=[{'name':'Form','endpoint_ids':['create'],'props':[{'name':'onSubmit','type':'function'}],'behavior':'A form'}]
    with pytest.raises(ValidationError):layout_proposal_schema(brief,design.api).model_validate(layout)
    tests=acceptance_fixture().model_dump();tests['scenarios'][0]['steps'][0]['operation_id']='not_declared'
    with pytest.raises(ValidationError):acceptance_schema(brief,design).model_validate(tests)
    tests=acceptance_fixture().model_dump();tests['scenarios'][-1]['steps'][0]['expected']={'length':1}
    with pytest.raises(ValidationError):acceptance_schema(brief,design).model_validate(tests)
    tests=acceptance_fixture().model_dump();tests['scenarios'][0]['steps'][0]['body']['amount']='{{capture}}'
    with pytest.raises(ValidationError):acceptance_schema(brief,design).model_validate(tests)
    # Error cases must still be able to exercise malformed business input.
    tests=acceptance_fixture().model_dump();tests['scenarios'][1]['steps'][0]['body']={'amount':'invalid'}
    assert acceptance_schema(brief,design).model_validate(tests)
    tests=acceptance_fixture().model_dump();tests['scenarios'][1]['steps'][0]['status']=422
    with pytest.raises(ValidationError):acceptance_schema(brief,design).model_validate(tests)
    endpoint=design.api.endpoints[-1].model_dump()
    endpoint['segments'][-1]['name']='another_method_chose_a_different_alias'
    from forge.contracts import Endpoint
    with pytest.raises(ValidationError):Endpoint.model_validate(endpoint)


def test_nested_dynamic_paths_have_one_mechanical_mapping():
    from forge.contracts import Endpoint
    endpoint=Endpoint(id='nested',method='GET',segments=[{'name':'parents','parameter':False},
        {'parameter':True},{'name':'children','parameter':False},{'parameter':True}],
        input_type='none',output_type='string',success_status=200,behavior='Read nested resource',requirement_ids=['R1'])
    assert endpoint.path=='/api/parents/{id}/children/{id2}'
    assert endpoint.file=='app/api/parents/[id]/children/[id2]/route.ts'
    assert endpoint.parameter_names==['id','id2']


def test_json_protocol_error_is_derived_without_rewriting_test_expectations():
    brief,design=design_fixture()
    data=design.api.endpoints[0].model_dump();data['error_statuses']=[]
    from forge.contracts import Endpoint
    operation=Endpoint.model_validate(data)
    assert operation.error_statuses==[400]
    assert Endpoint.model_validate(operation.model_dump()).error_statuses==[400]


@pytest.mark.parametrize('change',['unknown_type','duplicate_operation','unknown_component','wrong_page','unknown_requirement','missing_ui_operations'])
def test_structural_errors_stop_before_building(change):
    brief,design=design_fixture()
    if change=='unknown_type':design.api.endpoints[0].input_type='InventedInput'
    if change=='duplicate_operation':design.api.endpoints[-1].id='update'
    if change=='unknown_component':design.layout.pages[0].components=['NotDeclared']
    if change=='wrong_page':design.layout.pages[0].path='/extra'
    if change=='unknown_requirement':design.layout.pages[0].requirement_ids=['R99']
    if change=='missing_ui_operations':design.layout.pages[0].endpoint_ids=[]
    with pytest.raises(ValueError):compile_design(brief,design)


def test_test_compiler_uses_operation_contract_and_preserves_assertions():
    brief,design=design_fixture();recipe=acceptance_fixture()
    result=compile_acceptance(brief,design,recipe)
    assert result.scenarios[0].steps[0].path=='/api/entries'
    assert json.loads(result.scenarios[0].steps[0].expect_json)==recipe.scenarios[0].steps[0].expected
    update={'name':'Update','phase':'functional','requirement_ids':['R1'],'steps':[
        {'operation_id':'update','path_captures':[{'parameter':'id','capture':'entry_id'}],
         'body':{'amount':20},'expected':{'amount':20},'status':200}]}
    recipe.scenarios.insert(1,type(recipe.scenarios[0]).model_validate(update))
    result=compile_acceptance(brief,design,recipe)
    assert result.scenarios[1].steps[0].path=='/api/entries/{{entry_id}}'
    assert result.scenarios[1].steps[0].method=='PATCH'


def test_typed_subset_assertions_do_not_gain_default_null_fields():
    from forge.acceptance_design import acceptance_schema
    brief,design=design_fixture();recipe=acceptance_fixture().model_dump()
    recipe['scenarios'][0]['steps'][0]['expected']={'title':'Stored'}
    parsed=acceptance_schema(brief,design).model_validate(recipe)
    result=compile_acceptance(brief,design,parsed)
    assert json.loads(result.scenarios[0].steps[0].expect_json)=={'title':'Stored'}


@pytest.mark.parametrize('change',['array_as_object','unknown_operation','wrong_status','bad_pointer','uncaptured_path','unknown_field'])
def test_invalid_test_decisions_are_rejected_without_changing_them(change):
    brief,design=design_fixture();recipe=acceptance_fixture()
    if change=='array_as_object':recipe.scenarios[-1].steps[0].expected={'0':{'title':'Stored'}}
    if change=='unknown_operation':recipe.scenarios[0].steps[0].operation_id='invented'
    if change=='wrong_status':recipe.scenarios[0].steps[0].status=200
    if change=='bad_pointer':recipe.scenarios[0].steps[0].save_pointer='/missing'
    if change=='unknown_field':recipe.scenarios[0].steps[0].body['not_in_contract']=1
    if change=='uncaptured_path':
        step=recipe.scenarios[0].steps[0];step.operation_id='update';step.status=200
        step.path_captures=[ParameterCapture(parameter='id',capture='future')]
        recipe=AcceptanceDesign.model_validate(recipe.model_dump())
    before=recipe.model_dump()
    with pytest.raises(ValueError):compile_acceptance(brief,design,recipe)
    assert recipe.model_dump()==before


def test_context_uses_canonical_interfaces_without_duplicate_gold_tests(tmp_path):
    from forge.workspace import app_coding_context
    from forge.contracts import Helper
    brief,design=design_fixture()
    design.layout.helpers=[Helper(name='persistence',functions=[{'name':'load','returns':'Entry[]','behavior':'Read stored entries'}])]
    plan=compile_design(brief,design)
    req={**brief.model_dump(),'scenarios':compile_acceptance(brief,design,acceptance_fixture()).model_dump()['scenarios']}
    context=app_coding_context(req,plan.model_dump(),tmp_path,'app/api/entries/[id]/route.ts')
    assert {e['id'] for e in context['design']['operations']}=={'update','delete'}
    assert 'acceptance_examples' not in context['requirements']
    assert 'design' not in context['plan']
    assert 'EntryInput' in context['design']['platform_types']['lib/forge_contracts.ts']
    assert context['design']['brief_fingerprint']==design.brief_fingerprint
    assert context['design']['helpers'][0]['name']=='persistence'
    path=tmp_path/'app/api/entries/route.ts';path.parent.mkdir(parents=True)
    path.write_text('server database implementation',encoding='utf-8')
    frontend=app_coding_context(req,plan.model_dump(),tmp_path,'app/page.tsx')
    assert 'app/api/entries/route.ts' not in frontend['existing_source']
    assert frontend['design']['helpers']==[]


def test_handoff_and_actual_call_share_identity_and_inputs(tmp_path):
    from forge.persistence import JobStore
    from forge.handoffs import record_handoff
    from forge.agents import OllamaAgents
    store=JobStore(tmp_path/'jobs.db');job=store.create({'description':'Build a tool'})
    agent=OllamaAgents.__new__(OllamaAgents);agent.model_name='test';agent.trace_directory=tmp_path/'calls'
    agent.invocation_context={'job_id':job,'actor':'parent','task_id':'parent-task'}
    payload=record_handoff(store,job,'parent','child','Design API',{'file':'app/page.tsx','brief':'Original'},agents=agent)
    class Model:
        def with_structured_output(self,*_,**__):return self
        def invoke(self,messages):
            return {'raw':SimpleNamespace(content='{}',response_metadata={'done_reason':'stop','prompt_eval_count':42}),
                    'parsed':ApiDesign.model_validate(design_fixture(False)[1].api.model_dump()),'parsing_error':None}
    agent.model=Model()
    agent.generate(ApiDesign,'Decide API',{'value':'Exact input'})
    trace=json.loads(next((tmp_path/'calls').glob('*.json')).read_text())
    assert trace['handoff_id']==payload['handoff_id']
    assert trace['parent_task_id']=='parent-task'
    assert trace['input_sha256']==hashlib.sha256(json.dumps(trace['messages'],separators=(',',':')).encode()).hexdigest()
    assert json.loads(trace['messages'][1][1])=={'value':'Exact input'}
    assert trace['provider_metadata']['prompt_eval_count']==42


def test_corrupted_handoff_is_not_displayed_as_valid(tmp_path):
    from forge.handoffs import record_handoff,read_handoff
    from forge.persistence import JobStore
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    payload=record_handoff(store,job,'a','b','Read this',{'meaning':'original'})
    path=Path(payload['report'])
    assert read_handoff(path,payload)['context']['meaning']=='original'
    packet=json.loads(path.read_text());packet['context']['meaning']='different'
    path.write_text(json.dumps(packet),encoding='utf-8')
    with pytest.raises(ValueError,match='fingerprint'):read_handoff(path,payload)


@pytest.mark.parametrize('intent',['out_of_scope','help'])
def test_intake_answers_do_not_enter_app_planning(tmp_path,intent):
    from forge.agents import OllamaAgents
    from forge.contracts import IntakeDecision
    from forge.persistence import JobStore
    from forge.workflow import run_job
    agent=OllamaAgents.__new__(OllamaAgents);agent.model_name='qwen2.5-coder:7b';calls=[]
    def generate(schema,*args,**kwargs):
        calls.append(schema)
        assert schema is IntakeDecision
        return IntakeDecision.model_validate({'intent':intent,**({'topic':'workflow'} if intent=='help' else {})})
    agent.generate=generate
    store=JobStore(tmp_path/'jobs.db')
    result=run_job('How is the weather today?',agent,store)
    assert result['status']=='REQUEST_ANSWERED'
    assert calls==[IntakeDecision]
    assert not any(e['status'] in {'PLAN_REVIEW','BUILDING','REQUIREMENTS_READY'} for e in result['events'])


def test_real_planning_methods_share_the_compiled_contract_at_human_gate(tmp_path):
    from forge.agents import OllamaAgents
    from forge.contracts import IntakeDecision
    from forge.persistence import JobStore
    from forge.workflow import run_job,resume_job
    from forge.handoffs import record_handoff
    brief,design=design_fixture();recipe=acceptance_fixture()
    proposal=ApiProposal(records=[],operations=[{'id':action,'action':action,'entity':'entry',
        'behavior':action+' entries','requirement_ids':['R1','R2','R3','R4']}
        for action in ['create','list','update','delete']])
    design.api=compile_operations(brief,proposal)
    ready={key:value for key,value in brief.model_dump().items() if key not in {'spec_version','entities'}}
    responses={IntakeDecision:IntakeDecision.model_validate({'intent':'build'}),
               BusinessBrief:BusinessBrief.model_validate(ready),ApiProposal:proposal,
               LayoutProposal:LayoutProposal(pages=[p.model_dump() for p in design.layout.pages]),AcceptanceDesign:recipe}
    agent=OllamaAgents.__new__(OllamaAgents);agent.model_name='qwen2.5-coder:7b';calls=[]
    def generate(schema,instruction,data,**kwargs):
        key=next(key for key in responses if issubclass(schema,key))
        calls.append((key,copy.deepcopy(data)))
        return schema.model_validate(responses[key].model_dump())
    agent.generate=generate
    store=JobStore(tmp_path/'jobs.db')
    agent.handoff=lambda sender,recipient,summary,context:record_handoff(store,agent.invocation_context['job_id'],sender,recipient,summary,context,agents=agent)
    result=run_job('Build a record notebook with validation and persistence.',agent,store)
    assert result['status']=='PLAN_REVIEW'
    assert [schema for schema,_ in calls]==[IntakeDecision,BusinessBrief,ApiProposal,LayoutProposal,AcceptanceDesign]
    qa_input=calls[-1][1]
    assert [operation['id'] for operation in qa_input['api']['operations']]==['create','list','update','delete']
    handoffs=[e['payload'] for e in result['events'] if e['status']=='AGENT_HANDOFF']
    api_handoff=next(p for p in handoffs if p['recipient']=='api_architect')
    layout_handoff=next(p for p in handoffs if p['recipient']=='implementation_architect')
    assert layout_handoff['parent_task_id']==api_handoff['task_id']
    review=result['events'][-1]['payload']
    assert resume_job(result['job_id'],{'approved':True,'fingerprint':review['fingerprint']},None,store)['status']=='APPROVED'


def test_business_operation_adapter_derives_identity_and_http_contracts():
    brief=brief_fixture()
    proposal=proposal_schema(brief).model_validate({'records':[],'operations':[
        {'id':action+'_entry','action':action,'entity':'entry','behavior':action,'requirement_ids':['R1']}
        for action in ['create','list','read','update','delete']]})
    api=compile_operations(brief,proposal)
    assert [(e.method,e.path,e.input_type) for e in api.endpoints]==[
        ('POST','/api/create-entry','EntryInput'),('GET','/api/list-entry','none'),
        ('GET','/api/read-entry/{id}','none'),('POST','/api/update-entry','EntryUpdateInput'),
        ('POST','/api/delete-entry','EntryIdInput')]
    assert api.endpoints[-1].error_statuses==[400,404]
    invalid=proposal.model_dump();invalid['operations'][0]['entity']='unknown'
    with pytest.raises(ValidationError):proposal_schema(brief).model_validate(invalid)
    invalid=proposal.model_dump();invalid['operations'][1]['id']='create_entry'
    with pytest.raises(ValueError):compile_operations(brief,ApiProposal.model_validate(invalid))


def test_operation_and_layout_schemas_share_execution_file_limits():
    from forge.layout_design import layout_proposal_schema
    brief=brief_fixture()
    data={'records':[],'operations':[{'id':f'operation_{i}','action':'list','entity':'entry',
        'behavior':'Read entries','requirement_ids':['R1']} for i in range(11)]}
    with pytest.raises(ValidationError):proposal_schema(brief).model_validate(data)
    with pytest.raises(ValueError,match='file budget'):compile_operations(brief,ApiProposal.model_validate(data))
    data['operations'].pop();api=compile_operations(brief,ApiProposal.model_validate(data))
    schema=layout_proposal_schema(brief,api).model_json_schema()
    assert schema['properties']['helpers']['maxItems']==0
    assert schema['$defs']['BoundPageDecision']['properties']['components']['maxItems']==1


def test_compiled_identity_inputs_use_explicit_numeric_capture_bindings():
    brief,design=design_fixture();recipe=acceptance_fixture()
    design.api=compile_operations(brief,ApiProposal(records=[],operations=[
        {'id':action,'action':action,'entity':'entry','behavior':action,'requirement_ids':['R1']}
        for action in ['create','list','update','delete']]))
    update={'name':'Update','phase':'functional','requirement_ids':['R1'],'steps':[
        {'operation_id':'update','body':{'id':0,'amount':20},'status':200,'expected':{'amount':20},
         'body_bindings':[{'pointer':'/id','capture':'entry_id'}]}]}
    recipe.scenarios.insert(1,type(recipe.scenarios[0]).model_validate(update))
    step=compile_acceptance(brief,design,recipe).scenarios[1].steps[0]
    assert step.path=='/api/update' and step.method=='POST'
    assert json.loads(step.body_json)=={'id':0,'amount':20}
    assert step.body_bindings[0].capture=='entry_id'
    recipe.scenarios[1].steps[0].body['amount']=-1
    with pytest.raises(ValueError,match='lower bound'):compile_acceptance(brief,design,recipe)


def test_entity_effects_validate_lifecycle_without_guessing_from_http_methods():
    brief,design=design_fixture();recipe=acceptance_fixture()
    design.api=compile_operations(brief,ApiProposal(records=[],operations=[
        {'id':action,'action':action,'entity':'entry','behavior':action,'requirement_ids':['R1']}
        for action in ['create','list','delete']]))
    delete={'name':'Delete','phase':'functional','requirement_ids':['R1'],'steps':[
        {'operation_id':'delete','body':{'id':0},'status':204,'expected':None,
         'body_bindings':[{'pointer':'/id','capture':'entry_id'}]}]}
    recipe.scenarios.insert(1,type(recipe.scenarios[0]).model_validate(delete))
    with pytest.raises(ValueError,match='all captured fixtures were deleted'):
        compile_acceptance(brief,design,recipe)


def test_layout_interfaces_are_compiled_from_bound_operations():
    brief,design=design_fixture(False)
    proposal=LayoutProposal(pages=[{**design.layout.pages[0].model_dump(),'endpoint_ids':[],
        'components':[{'name':'Form','endpoint_ids':['create'],'behavior':'Enter a value and show its calculated result'}]}],
        helpers=[{'name':'calculation','endpoint_ids':['create']}])
    layout=compile_layout(design.api,proposal)
    callback=layout.components[0].callbacks[0];helper=layout.helpers[0].functions[0]
    assert callback.name=='on_create' and helper.name=='handle_create'
    assert callback.parameters==helper.parameters
    assert callback.parameters[0].type=='CalculationInput'
    assert callback.returns==helper.returns=='CalculationResult'
    assert layout.components[0].props[0].name=='result_create'
    assert layout.components[0].props[0].type=='CalculationResult'
    assert layout.pages[0].components==['Form'] and layout.pages[0].endpoint_ids==['create']
    proposal.helpers.append(proposal.helpers[0].model_copy(update={'name':'duplicate_owner'}))
    with pytest.raises(ValueError,match='one server-helper owner'):compile_layout(design.api,proposal)
