"""Compile operation-referenced test decisions into the trusted runner's wire format."""
import json
import math
from typing import Annotated, Literal, Union

from pydantic import Field, JsonValue, StrictBool, StrictFloat, StrictInt, StrictStr, create_model

from forge.contracts import Contract, Identifier, entity_type, validate_api


class ParameterCapture(Contract):
    parameter: str
    capture: Identifier


class JsonBinding(Contract):
    pointer: str
    capture: Identifier


class TestStep(Contract):
    operation_id: Identifier
    body: JsonValue
    expected: JsonValue
    status: int = Field(ge=200, le=499)
    path_captures: list[ParameterCapture] = Field(default_factory=list, max_length=5)
    save_as: str = ''
    save_pointer: str = ''
    body_bindings: list[JsonBinding] = Field(default_factory=list, max_length=8)
    expect_bindings: list[JsonBinding] = Field(default_factory=list, max_length=8)


class TestCase(Contract):
    name: str = Field(min_length=1, max_length=100)
    phase: Literal['functional', 'restart']
    requirement_ids: list[str] = Field(min_length=1, max_length=15)
    steps: list[TestStep] = Field(min_length=1, max_length=8)


class AcceptanceDesign(Contract):
    scenarios: list[TestCase] = Field(min_length=2, max_length=10)


def acceptance_schema(brief,design):
    """Test selection uses accepted operation/requirement IDs, not a new naming decision."""
    shapes,_=validate_api(brief,design.api)
    cached={}
    def fixture_type(name,partial=False):
        if name=='none':return type(None)
        if name.endswith('[]'):return list[fixture_type(name[:-2],partial)]
        primitive={'string':StrictStr,'number':StrictInt | StrictFloat,'boolean':StrictBool}
        if name in primitive:return primitive[name]
        key=(name,partial)
        if key not in cached:
            fields={}
            for field in shapes[name].fields:
                value=fixture_type(field.type,partial)
                if field.nullable:value=value | None
                # Omitted subset assertions remain omitted on serialization; explicit
                # null is allowed only when the contract itself permits null.
                fields[field.name]=(value,None if partial or not field.required else ...)
            cached[key]=create_model(('Expected_' if partial else 'Input_')+name,__base__=Contract,**fields)
        return cached[key]
    params=tuple(sorted({name for e in design.api.endpoints for name in e.parameter_names}))
    capture=create_model('KnownParameterCapture',__base__=ParameterCapture,
        parameter=(Literal[params],...)) if params else ParameterCapture
    variants=[]
    for endpoint in design.api.endpoints:
        shared=dict(
            operation_id=(Literal[endpoint.id],...),
            path_captures=(list[capture],Field(default_factory=list,max_length=len(endpoint.parameter_names))))
        success=create_model('Success_'+endpoint.id,__base__=TestStep,**shared,
            status=(Literal[endpoint.success_status],...),
            body=(fixture_type(endpoint.input_type),...),
            expected=(fixture_type(endpoint.output_type,True) | None,...))
        if endpoint.error_statuses:
            error=create_model('Error_'+endpoint.id,__base__=TestStep,**shared,
                status=(Literal[tuple(endpoint.error_statuses)],...))
            variants.append(Annotated[success | error,Field(discriminator='status')])
        else:variants.append(success)
    if len(variants)==1:step=variants[0]
    else:
        step=Annotated[Union[tuple(variants)],Field(discriminator='operation_id')]
    case=create_model('OperationTestCase',__base__=TestCase,
        requirement_ids=(list[Literal[tuple(f'R{i+1}' for i in range(len(brief.acceptance_criteria)))]],Field(min_length=1,max_length=15)),
        steps=(list[step],Field(min_length=1,max_length=8)))
    return create_model('AcceptanceDesign',__base__=AcceptanceDesign,
        scenarios=(list[case],Field(min_length=2,max_length=10)))


def check_value(value, type_name, shapes, *, subset=False):
    if type_name=='none':
        if value is not None:raise ValueError('Bodyless responses/requests cannot assert JSON content')
        return
    if type_name.endswith('[]'):
        if not isinstance(value,list):raise ValueError(f'{type_name} expects a JSON array, not an object')
        for item in value:check_value(item,type_name[:-2],shapes,subset=subset)
    elif type_name in shapes:
        if not isinstance(value,dict):raise ValueError(f'{type_name} expects a JSON object')
        fields={field.name:field for field in shapes[type_name].fields}
        if set(value)-set(fields):raise ValueError(f'{type_name} has unknown fields: '+', '.join(sorted(set(value)-set(fields))))
        if not subset and any(field.required and field.name not in value for field in fields.values()):raise ValueError(f'{type_name} fixture is missing required fields')
        for name,item in value.items():
            field=fields[name]
            if item is None and field.nullable:continue
            check_value(item,field.type,shapes,subset=subset)
    elif type_name=='number':
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('Expected a finite JSON number')
    elif type_name=='boolean':
        if not isinstance(value,bool):raise ValueError('Expected a JSON boolean')
    elif type_name=='string':
        if not isinstance(value,str):raise ValueError('Expected a JSON string')
    else:raise ValueError(f'Unknown test contract type: {type_name}')


def pointer_type(type_name,pointer,shapes):
    if not pointer.startswith('/'):raise ValueError('Fixture pointers must be JSON pointers')
    for key in pointer.split('/')[1:]:
        key=key.replace('~1','/').replace('~0','~')
        if type_name.endswith('[]') and key.isdigit():type_name=type_name[:-2]
        elif type_name in shapes:
            fields={field.name:field for field in shapes[type_name].fields}
            if key not in fields:raise ValueError(f'Pointer {pointer} is absent from {type_name}')
            type_name=fields[key].type
        else:raise ValueError(f'Pointer {pointer} does not resolve through the declared JSON type')
    return type_name


def check_business_input(brief,type_name,body,bindings):
    if brief.data_contract is None or not isinstance(body,dict):return
    bound={binding.pointer for binding in bindings}
    for entity in brief.data_contract.entities:
        if type_name not in {entity_type(entity.name)+suffix for suffix in ('Input','Patch','UpdateInput','IdInput')}:continue
        for field in entity.fields:
            if field.name not in body or '/'+field.name in bound or body[field.name] is None:continue
            value=body[field.name]
            if field.kind=='enum' and value not in field.choices:raise ValueError(f'{field.name}: positive fixture is outside declared enum choices')
            if field.kind=='number':
                if field.lower and (value<field.lower.value or value==field.lower.value and not field.lower.inclusive):raise ValueError(f'{field.name}: positive fixture violates the lower bound')
                if field.upper and (value>field.upper.value or value==field.upper.value and not field.upper.inclusive):raise ValueError(f'{field.name}: positive fixture violates the upper bound')
            if field.kind in {'text','date'}:
                if field.min_length is not None and len(value)<field.min_length:raise ValueError(f'{field.name}: positive fixture is too short')
                if field.max_length is not None and len(value)>field.max_length:raise ValueError(f'{field.name}: positive fixture is too long')
            if field.kind=='reference' and (not isinstance(value,int) or isinstance(value,bool) or value<1):raise ValueError(f'{field.name}: references use positive integer IDs')


def compile_acceptance(brief, design, proposal):
    from forge.schemas import AppAcceptancePlan
    # Dynamic model-visible fixture schemas are projected without introducing
    # defaults into the independently chosen request/assertion values.
    proposal=AcceptanceDesign.model_validate(proposal.model_dump(exclude_unset=True))
    shapes,_=validate_api(brief,design.api)
    endpoints={endpoint.id:endpoint for endpoint in design.api.endpoints}
    requirements={f'R{i+1}' for i in range(len(brief.acceptance_criteria))}
    scenarios=[]
    captures={}
    records={};unknown_entities=set()
    ordered=[s for phase in ('functional','restart') for s in proposal.scenarios if s.phase==phase]
    for scenario in ordered:
        if not set(scenario.requirement_ids)<=requirements:raise ValueError('Test refers to an unknown requirement ID')
        steps=[]
        for step in scenario.steps:
            if step.operation_id not in endpoints:raise ValueError(f'Unknown test operation: {step.operation_id}')
            endpoint=endpoints[step.operation_id]
            effect=endpoint.effect
            if effect and step.status==endpoint.success_status:
                if scenario.phase=='functional' and effect.action=='create':
                    if step.save_as and step.save_pointer=='/id':
                        if step.save_as in records:unknown_entities.add(records[step.save_as][0])
                        records[step.save_as]=[effect.entity,True]
                    else:unknown_entities.add(effect.entity)
                if scenario.phase=='functional' and effect.action=='delete':
                    identity=next((binding.capture for binding in step.body_bindings if binding.pointer=='/id'),None)
                    if identity in records and records[identity][0]==effect.entity:records[identity][1]=False
                    else:unknown_entities.add(effect.entity)
                if scenario.phase=='restart' and effect.action in {'list','read'} and step.expected:
                    known=[alive for entity,alive in records.values() if entity==effect.entity]
                    if known and not any(known) and effect.entity not in unknown_entities:
                        raise ValueError(f'Restart expects {effect.entity} records after all captured fixtures were deleted; retain a separate fixture')
            if step.status<300:
                if step.status!=endpoint.success_status:raise ValueError(f'{endpoint.id}: expected success status differs from the operation contract')
                if endpoint.input_type!='none':
                    check_value(step.body,endpoint.input_type,shapes)
                    check_business_input(brief,endpoint.input_type,step.body,step.body_bindings)
                elif step.body is not None:raise ValueError('This operation has no input body')
                if step.expected is not None:check_value(step.expected,endpoint.output_type,shapes,subset=True)
            elif step.status not in endpoint.error_statuses:
                raise ValueError(f'{endpoint.id}: expected error status is not declared in the operation contract')
            bindings={binding.parameter:binding.capture for binding in step.path_captures}
            parameters=set(endpoint.parameter_names)
            if len(bindings)!=len(step.path_captures) or set(bindings)!=parameters:
                raise ValueError(f'{endpoint.id}: supply exactly one capture for each path parameter: '+', '.join(sorted(parameters)))
            if any(name not in captures for name in bindings.values()):raise ValueError('Path captures must be created before use')
            for type_name,bindings_list in [(endpoint.input_type,step.body_bindings),(endpoint.output_type,step.expect_bindings)]:
                for binding in bindings_list:
                    if binding.capture not in captures:raise ValueError('JSON captures must be created before use')
                    if pointer_type(type_name,binding.pointer,shapes)!=captures[binding.capture]:raise ValueError('Captured value type differs from the JSON fixture field')
            names=iter(endpoint.parameter_names)
            path='/api/'+'/'.join('{{'+bindings[next(names)]+'}}' if s.parameter else s.name for s in endpoint.segments)
            steps.append({'method':endpoint.method,'path':path,'status':step.status,
                'body_json':json.dumps(step.body,separators=(',',':')) if step.body is not None else '',
                'expect_json':json.dumps(step.expected,separators=(',',':')) if step.expected is not None else '',
                'save_as':step.save_as,'save_pointer':step.save_pointer,
                'body_bindings':[b.model_dump() for b in step.body_bindings],
                'expect_bindings':[b.model_dump() for b in step.expect_bindings]})
            if step.save_as:
                if step.status>=300:raise ValueError('Captures require a declared successful response type')
                saved_type=pointer_type(endpoint.output_type,step.save_pointer,shapes)
                if saved_type not in {'number','string'}:raise ValueError('Only scalar string/number captures are supported')
                captures[step.save_as]=saved_type
        scenarios.append({'name':scenario.name,'phase':scenario.phase,'steps':steps})
    return AppAcceptancePlan(database=brief.database,scenarios=scenarios)
