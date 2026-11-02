"""Business-operation decisions compiled into a fixed JSON HTTP adapter.

No app names or domain-specific route templates are used here.
"""
from typing import Annotated,Literal

from pydantic import Field,create_model

from forge.contracts import (Contract,Identifier,TypeRef,RecordShape,Endpoint,
                             ApiDesign,entity_type,validate_api)


class Operation(Contract):
    id: Identifier
    behavior: str = Field(min_length=1,max_length=500)
    requirement_ids: list[str] = Field(min_length=1,max_length=15)


class EntityOperation(Operation):
    action: Literal['create','list','read','update','delete']
    entity: Identifier


class CustomOperation(Operation):
    action: Literal['custom']
    input_type: TypeRef
    output_type: TypeRef
    read_only: bool
    success_status: int = Field(ge=200,le=299)
    error_statuses: list[int] = Field(default_factory=list,max_length=5)


class ApiProposal(Contract):
    records: list[RecordShape] = Field(max_length=8,description='Required: define every extra input/output record referenced by custom operations, including its fields. Use [] only when all types are already provided.')
    operations: list[Annotated[EntityOperation | CustomOperation,Field(discriminator='action')]] = Field(min_length=1,max_length=15)


def proposal_schema(brief):
    requirements=Literal[tuple(f'R{i+1}' for i in range(len(brief.acceptance_criteria)))]
    custom=create_model('CustomDecision',__base__=CustomOperation,
        requirement_ids=(list[requirements],Field(min_length=1,max_length=15)))
    names=tuple(entity.name for entity in brief.data_contract.entities)
    if names:
        entity=create_model('EntityDecision',__base__=EntityOperation,entity=(Literal[names],...),
            requirement_ids=(list[requirements],Field(min_length=1,max_length=15)))
        operation=Annotated[entity | custom,Field(discriminator='action')]
    else:operation=custom
    return create_model('ApiProposal',__base__=ApiProposal,
        operations=(list[operation],Field(min_length=1,max_length=min(10,12-len(brief.pages)))))


def compile_operations(brief,proposal):
    if len(proposal.operations)>min(10,12-len(brief.pages)):
        raise ValueError('Operation count exceeds the small-app file budget, including the approved pages')
    names={entity.name for entity in brief.data_contract.entities}
    endpoints=[]
    for operation in proposal.operations:
        segments=[{'name':operation.id.replace('_','-'),'parameter':False}]
        if isinstance(operation,EntityOperation):
            if operation.entity not in names:raise ValueError('Operation targets an unknown entity')
            name=entity_type(operation.entity)
            method='GET' if operation.action in {'list','read'} else 'POST'
            input_type={'create':name+'Input','update':name+'UpdateInput','delete':name+'IdInput'}.get(operation.action,'none')
            output_type=name+'[]' if operation.action=='list' else 'none' if operation.action=='delete' else name
            if operation.action=='read':segments.append({'parameter':True})
            status={'create':201,'delete':204}.get(operation.action,200)
            errors=[404] if operation.action in {'read','update','delete'} else []
        else:
            method='GET' if operation.read_only and operation.input_type=='none' else 'POST'
            input_type='EmptyInput' if method=='POST' and operation.input_type=='none' else operation.input_type
            output_type=operation.output_type;status=operation.success_status;errors=operation.error_statuses
        endpoints.append(Endpoint(id=operation.id,method=method,segments=segments,input_type=input_type,
            output_type=output_type,success_status=status,error_statuses=errors,
            behavior=operation.behavior,requirement_ids=operation.requirement_ids,
            effect={'entity':operation.entity,'action':operation.action} if isinstance(operation,EntityOperation) else None))
    api=ApiDesign(records=proposal.records,endpoints=endpoints)
    validate_api(brief,api)
    return api
