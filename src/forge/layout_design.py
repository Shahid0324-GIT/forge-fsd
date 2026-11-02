"""Compile layout bindings into interfaces; models do not redefine operation signatures."""
from typing import Literal

from pydantic import Field,create_model

from forge.contracts import Contract,Identifier,TypeName,Page,LayoutDesign


class BoundComponent(Contract):
    name: TypeName
    endpoint_ids: list[Identifier] = Field(min_length=1,max_length=10)
    behavior: str = Field(min_length=1,max_length=500)


class BoundHelper(Contract):
    name: Identifier
    endpoint_ids: list[Identifier] = Field(min_length=1,max_length=8)


class BoundPage(Contract):
    path: str
    components: list[BoundComponent] = Field(default_factory=list,max_length=4)
    endpoint_ids: list[Identifier] = Field(default_factory=list,max_length=15)
    behavior: str = Field(min_length=1,max_length=500)
    requirement_ids: list[str] = Field(min_length=1,max_length=15)


class LayoutProposal(Contract):
    pages: list[BoundPage] = Field(min_length=1,max_length=5)
    helpers: list[BoundHelper] = Field(default_factory=list,max_length=3)


def layout_proposal_schema(brief,api):
    operation=Literal[tuple(endpoint.id for endpoint in api.endpoints)]
    requirement=Literal[tuple(f'R{i+1}' for i in range(len(brief.acceptance_criteria)))]
    component=create_model('BoundComponentDecision',__base__=BoundComponent,
        endpoint_ids=(list[operation],Field(min_length=1,max_length=10)))
    helper=create_model('BoundHelperDecision',__base__=BoundHelper,
        endpoint_ids=(list[operation],Field(min_length=1,max_length=8)))
    files=len({endpoint.file for endpoint in api.endpoints})
    remaining=max(0,12-files-len(brief.pages))
    page=create_model('BoundPageDecision',__base__=BoundPage,path=(Literal[tuple(brief.pages)],...),
        components=(list[component],Field(default_factory=list,max_length=min(4,remaining))),
        endpoint_ids=(list[operation],Field(default_factory=list,max_length=15)),
        requirement_ids=(list[requirement],Field(min_length=1,max_length=15)))
    return create_model('LayoutProposal',__base__=LayoutProposal,
        pages=(list[page],Field(min_length=len(brief.pages),max_length=len(brief.pages))),
        helpers=(list[helper],Field(default_factory=list,max_length=min(3,remaining,max(0,10-files)))))


def compile_layout(api,proposal):
    endpoints={endpoint.id:endpoint for endpoint in api.endpoints}
    def selected(ids):
        if len(set(ids))!=len(ids) or not set(ids)<=set(endpoints):
            raise ValueError('Layout bindings require unique, known operation IDs')
        return [endpoints[name] for name in ids]
    def parameters(endpoint):
        return ([{'name':name,'type':'number'} for name in endpoint.parameter_names]+
                ([{'name':'input','type':endpoint.input_type}] if endpoint.input_type!='none' else []))
    declarations={};pages=[]
    for page in proposal.pages:
        ids=list(page.endpoint_ids)
        for component in page.components:
            if component.name in declarations and declarations[component.name]!=component:
                raise ValueError('A shared component name must have one consistent declaration')
            declarations[component.name]=component
            ids.extend(component.endpoint_ids)
        pages.append(Page(path=page.path,components=[c.name for c in page.components],
            endpoint_ids=list(dict.fromkeys(ids)),behavior=page.behavior,requirement_ids=page.requirement_ids))
    components=[]
    for component in declarations.values():
        operations=selected(component.endpoint_ids)
        components.append({'name':component.name,'behavior':component.behavior,
            'props':[{'name':'result_'+e.id,'type':e.output_type,'required':False,'nullable':True}
                     for e in operations if e.output_type!='none'],
            'callbacks':[{'name':'on_'+e.id,'parameters':parameters(e),
                'returns':'void' if e.output_type=='none' else e.output_type,'asynchronous':True,
                'behavior':e.behavior} for e in operations]})
    helpers=[];assigned=set()
    for helper in proposal.helpers:
        if assigned & set(helper.endpoint_ids):raise ValueError('An operation can have only one server-helper owner')
        assigned.update(helper.endpoint_ids)
        helpers.append({'name':helper.name,'functions':[{'name':'handle_'+e.id,
            'parameters':parameters(e),'returns':'void' if e.output_type=='none' else e.output_type,
            'asynchronous':False,'behavior':e.behavior} for e in selected(helper.endpoint_ids)]})
    return LayoutDesign(pages=pages,components=components,helpers=helpers)
