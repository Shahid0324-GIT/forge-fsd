"""Versioned, app-independent decisions. Framework paths are compiled, never guessed."""
import hashlib
import json
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


Identifier = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]{0,31}$')]
TypeName = Annotated[str, Field(pattern=r'^[A-Z][A-Za-z0-9]{0,63}$')]
TypeRef = Annotated[str, Field(pattern=r'^[A-Za-z][A-Za-z0-9]*(?:\[\])?$')]


class FieldBase(Contract):
    name: Identifier
    required: bool
    unique: bool = Field(description='Whether the business request requires this field to be unique across records')

    @model_validator(mode='after')
    def business_field(self):
        if self.name=='id':raise ValueError('id is supplied by the platform; list business fields only')
        return self


class StringField(FieldBase):
    kind: Literal['text','date']
    min_length: int | None = Field(default=None,ge=0)
    max_length: int | None = Field(default=None,ge=1)

    @model_validator(mode='after')
    def valid_lengths(self):
        if self.min_length is not None and self.max_length is not None and self.min_length>self.max_length:
            raise ValueError('min_length exceeds max_length')
        return self


class NumericBound(Contract):
    value: float
    inclusive: bool = True


class NumberField(FieldBase):
    kind: Literal['number']
    lower: NumericBound | None = None
    upper: NumericBound | None = None

    @model_validator(mode='after')
    def valid_range(self):
        if self.lower and self.upper:
            if self.lower.value>self.upper.value or (self.lower.value==self.upper.value and not (self.lower.inclusive and self.upper.inclusive)):
                raise ValueError('Numeric bounds describe an empty range')
        return self


class BooleanField(FieldBase):
    kind: Literal['boolean']


class EnumField(FieldBase):
    kind: Literal['enum']
    choices: list[Annotated[str,Field(min_length=1,max_length=80)]] = Field(min_length=1,max_length=20)

    @model_validator(mode='after')
    def unique_choices(self):
        if len(set(self.choices))!=len(self.choices):raise ValueError('Enum choices must be unique')
        return self


class ReferenceField(FieldBase):
    kind: Literal['reference']
    reference: Identifier


StoredField = Annotated[StringField | NumberField | BooleanField | EnumField | ReferenceField,Field(discriminator='kind')]


class Entity(Contract):
    name: Identifier
    fields: list[StoredField] = Field(min_length=1, max_length=8)


class ComputedOutput(Contract):
    name: Identifier
    description: str = Field(min_length=1, max_length=400)


class DataContract(Contract):
    entities: list[Entity] = Field(max_length=3)
    computed_outputs: list[ComputedOutput] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def references_exist(self):
        names = [entity.name for entity in self.entities]
        if len(names) != len(set(names)):
            raise ValueError('Entity names must be unique')
        for entity in self.entities:
            fields = [field.name for field in entity.fields]
            if len(fields) != len(set(fields)):
                raise ValueError(f'{entity.name}: field names must be unique')
            for field in entity.fields:
                if getattr(field,'reference','') and field.reference not in names:
                    raise ValueError(f'{entity.name}.{field.name}: unknown reference {field.reference}')
        return self


class BriefFields(Contract):
    title: str = Field(min_length=1, max_length=160)
    acceptance_criteria: list[str] = Field(min_length=4, max_length=15)
    assumptions: list[str] = Field(max_length=8)
    open_questions: list[str] = Field(default_factory=list,max_length=0,description='The intake stage handles blocking questions; ready briefs do not ask additional questions')
    database: Literal['sqlite', 'none']
    pages: list[str] = Field(min_length=1, max_length=5, description='Static page paths, including /; not API paths')
    data_contract: DataContract

    @model_validator(mode='after')
    def supported_business_scope(self):
        if (self.database=='sqlite') != bool(self.data_contract.entities):
            raise ValueError('SQLite requires stored entities; database=none must not declare stored entities')
        if '/' not in self.pages or len(set(self.pages))!=len(self.pages) or any(not re.fullmatch(r'/(?:[a-z][a-z0-9-]*(?:/[a-z][a-z0-9-]*)*)?',page) or page=='/api' or page.startswith('/api/') for page in self.pages):
            raise ValueError('Pages must be unique static paths including /; API paths are compiled separately')
        self.to_brief()
        return self

    def to_brief(self):
        from forge.schemas import AppBrief
        entities = []
        for entity in self.data_contract.entities:
            fields = []
            for field in entity.fields:
                rules = field.model_dump(exclude={'name', 'kind', 'required', 'choices'}, exclude_none=True)
                if getattr(field,'choices',[]):rules['choices']='See authoritative data_contract'
                fields.append({'name': field.name, 'kind': field.kind, 'required': field.required,
                               'constraints': json.dumps(rules, separators=(',', ':'))})
            entities.append({'name': entity.name, 'fields': fields,
                             'relationships': ', '.join(f'{f.name}->{f.reference}' for f in entity.fields if getattr(f,'reference',''))})
        return AppBrief(spec_version=2, **self.model_dump(exclude={'data_contract'}),
                        entities=entities, data_contract=self.data_contract)


class StatelessData(DataContract):
    entities: list[Entity] = Field(default_factory=list,max_length=0)


class StoredData(DataContract):
    entities: list[Entity] = Field(min_length=1,max_length=3)


class StatelessBrief(BriefFields):
    database: Literal['none']
    data_contract: StatelessData


class PersistentBrief(BriefFields):
    database: Literal['sqlite']
    data_contract: StoredData


class BusinessBrief(RootModel[Annotated[StatelessBrief | PersistentBrief,Field(discriminator='database')]]):
    def to_brief(self):
        return self.root.to_brief()


class BuildIntent(Contract):
    intent: Literal['build']


class ClarifyIntent(Contract):
    intent: Literal['clarify']
    blocking_reason: str = Field(min_length=1,max_length=300)
    questions: list[str] = Field(min_length=1,max_length=3)


class AnsweredIntent(Contract):
    intent: Literal['help','out_of_scope']
    message: str = Field(min_length=1,max_length=1000)


class HelpIntent(Contract):
    intent: Literal['help']
    topic: Literal['workflow','capabilities','approvals','status']


class OutOfScopeIntent(Contract):
    intent: Literal['out_of_scope']


class IntakeDecision(RootModel[Annotated[BuildIntent | ClarifyIntent | HelpIntent | OutOfScopeIntent,Field(discriminator='intent')]]):
    pass


class ShapeField(Contract):
    name: Annotated[str, Field(pattern=r'^[a-zA-Z][a-zA-Z0-9_]{0,39}$')]
    type: TypeRef
    required: bool = True
    nullable: bool = False


class RecordShape(Contract):
    name: TypeName
    fields: list[ShapeField] = Field(max_length=12)


class LiteralSegment(Contract):
    name: Annotated[str, Field(pattern=r'^[a-z][a-z0-9-]{0,31}$')]
    parameter: Literal[False]


class ParameterSegment(Contract):
    parameter: Literal[True]


Segment = Annotated[LiteralSegment | ParameterSegment,Field(discriminator='parameter')]


class EntityEffect(Contract):
    action: Literal['create','list','read','update','delete']
    entity: Identifier


class Endpoint(Contract):
    id: Identifier
    method: Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
    segments: list[Segment] = Field(min_length=1, max_length=5, description='Segments AFTER /api; parameter=true for dynamic values; do not write framework paths')
    input_type: TypeRef = Field(description='Known record type or none for no body')
    output_type: TypeRef = Field(description='Known type, array type, or none for no response body')
    success_status: int = Field(ge=200, le=299)
    error_statuses: list[int] = Field(default_factory=list, max_length=5,description='Business 4xx errors; JSON input validation 400 is added by the platform')
    behavior: str = Field(min_length=1, max_length=500)
    requirement_ids: list[str] = Field(min_length=1, max_length=15)
    effect: EntityEffect | None = None

    @model_validator(mode='after')
    def protocol_errors(self):
        # The trusted runner requires JSON endpoints to reject malformed/null input.
        # This is a shared protocol guarantee, not a model-selected business decision.
        self.error_statuses=sorted(set(self.error_statuses)|({400} if self.input_type!='none' else set()))
        if len(self.error_statuses)>5:raise ValueError('At most five error codes are supported, including protocol validation errors')
        return self

    @property
    def path(self):
        names=iter(self.parameter_names)
        return '/api/' + '/'.join('{'+next(names)+'}' if s.parameter else s.name for s in self.segments)

    @property
    def file(self):
        names=iter(self.parameter_names)
        return 'app/api/' + '/'.join('['+next(names)+']' if s.parameter else s.name for s in self.segments) + '/route.ts'

    @property
    def parameter_names(self):
        return ['id' if index==0 else f'id{index+1}' for index in range(sum(s.parameter for s in self.segments))]


class ApiDesign(Contract):
    records: list[RecordShape] = Field(default_factory=list, max_length=8, description='Extra DTOs; entity read/Input/Patch types are already provided')
    endpoints: list[Endpoint] = Field(min_length=1, max_length=15)


class FunctionInterface(Contract):
    name: Annotated[str, Field(pattern=r'^[a-z][a-zA-Z0-9_]{0,39}$')]
    parameters: list[ShapeField] = Field(default_factory=list, max_length=8)
    returns: TypeRef
    asynchronous: bool = False
    behavior: str = Field(min_length=1, max_length=400)


class Helper(Contract):
    name: Identifier
    functions: list[FunctionInterface] = Field(min_length=1, max_length=8)


class Component(Contract):
    name: TypeName
    props: list[ShapeField] = Field(default_factory=list, max_length=8)
    callbacks: list[FunctionInterface] = Field(default_factory=list, max_length=5)
    behavior: str = Field(min_length=1, max_length=500)


class Page(Contract):
    path: str = Field(description='One of the approved page paths')
    components: list[str] = Field(default_factory=list, max_length=6)
    endpoint_ids: list[str] = Field(default_factory=list, max_length=15)
    behavior: str = Field(min_length=1, max_length=700)
    requirement_ids: list[str] = Field(min_length=1, max_length=15)


class LayoutDesign(Contract):
    pages: list[Page] = Field(min_length=1, max_length=5)
    components: list[Component] = Field(default_factory=list, max_length=4)
    helpers: list[Helper] = Field(default_factory=list, max_length=3)


class AppDesign(Contract):
    version: Literal[1] = 1
    brief_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    api: ApiDesign
    layout: LayoutDesign


def brief_fingerprint(brief):
    names = ['spec_version', 'title', 'acceptance_criteria', 'assumptions', 'open_questions', 'database', 'pages', 'entities', 'data_contract']
    data = brief.model_dump() if hasattr(brief, 'model_dump') else brief
    canonical = {name: data.get(name) for name in names}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def entity_type(name):
    return ''.join(part.capitalize() for part in name.split('_'))


def record_shapes(data_contract):
    result = {'EmptyInput':RecordShape(name='EmptyInput',fields=[])}
    if data_contract is None:
        return result
    for entity in data_contract.entities:
        fields = [ShapeField(name=f.name, type={'number':'number','reference':'number','boolean':'boolean'}.get(f.kind, 'string'),
                             required=f.required, nullable=not f.required) for f in entity.fields]
        name = entity_type(entity.name)
        if any(key in result for key in [name,name+'Input',name+'Patch',name+'IdInput',name+'UpdateInput']):raise ValueError('Entity names collide in generated type names')
        result[name] = RecordShape(name=name, fields=[ShapeField(name='id', type='number'),
            *[f.model_copy(update={'required':True}) for f in fields]])
        result[name+'Input'] = RecordShape(name=name+'Input', fields=fields)
        result[name+'Patch'] = RecordShape(name=name+'Patch', fields=[f.model_copy(update={'required':False}) for f in fields])
        result[name+'IdInput']=RecordShape(name=name+'IdInput',fields=[ShapeField(name='id',type='number')])
        result[name+'UpdateInput']=RecordShape(name=name+'UpdateInput',fields=[ShapeField(name='id',type='number'),
            *[f.model_copy(update={'required':False}) for f in fields]])
    return result


def all_shapes(brief, api):
    shapes = record_shapes(brief.data_contract)
    for record in api.records:
        if record.name in shapes:
            raise ValueError(f'Duplicate or platform-defined record type: {record.name}')
        shapes[record.name] = record
    return shapes


def validate_api(brief, api):
    shapes = all_shapes(brief, api)
    known = {'string', 'number', 'boolean', *shapes}
    def check_type(value, none=False, void=False):
        base = value.removesuffix('[]')
        if base not in known and not (none and value == 'none') and not (void and value == 'void'):
            raise ValueError(f'Unknown type {value}; use declared DTO/entity types or primitives')
    for shape in shapes.values():
        if len({f.name for f in shape.fields}) != len(shape.fields):
            raise ValueError(f'{shape.name}: duplicate fields')
        for field in shape.fields:check_type(field.type)
    # Recursive DTOs cannot be finitely exercised by this bounded JSON contract.
    visited=set()
    def visit(name, stack):
        if name in stack:raise ValueError('Recursive DTO records are unsupported')
        if name in visited:return
        for field in shapes[name].fields:
            child=field.type.removesuffix('[]')
            if child in shapes:visit(child, stack | {name})
        visited.add(name)
    for name in shapes:visit(name, set())
    ids=set();routes=set();requirements={f'R{i+1}' for i in range(len(brief.acceptance_criteria))}
    for endpoint in api.endpoints:
        if endpoint.id in ids or (endpoint.method, endpoint.path) in routes:
            raise ValueError('Endpoint IDs and method/path pairs must be unique')
        ids.add(endpoint.id);routes.add((endpoint.method, endpoint.path))
        if any(code<400 or code>499 for code in endpoint.error_statuses):raise ValueError('Expected error statuses must be 4xx')
        if not set(endpoint.requirement_ids)<=requirements:raise ValueError('Endpoint refers to unknown requirement IDs')
        if endpoint.method=='GET' and endpoint.input_type!='none':raise ValueError('GET endpoints cannot have request bodies')
        if endpoint.method in {'POST','PUT','PATCH'} and endpoint.input_type=='none':
            raise ValueError('JSON mutation endpoints need an input record; declare an empty record for an action with no fields')
        check_type(endpoint.input_type, none=True);check_type(endpoint.output_type, none=True)
        if endpoint.input_type!='none' and endpoint.input_type not in shapes:raise ValueError('JSON request bodies must use a declared record type')
        if endpoint.success_status==204 and endpoint.output_type!='none':raise ValueError('HTTP 204 has no response body')
    return shapes, check_type


def compile_design(brief, design):
    """Render the legacy execution contract from one validated design; no business-code synthesis."""
    from forge.schemas import ImplementationPlan
    if brief.data_contract is None:raise ValueError('A typed app design requires a typed business data contract')
    if design.brief_fingerprint != brief_fingerprint(brief):raise ValueError('Design belongs to a different business brief')
    shapes, check_type = validate_api(brief, design.api)
    layout=design.layout
    if sorted(p.path for p in layout.pages)!=sorted(brief.pages):raise ValueError('Layout must implement exactly the approved pages')
    names=[c.name for c in layout.components]
    if len(names)!=len(set(names)):raise ValueError('Component names must be unique')
    helper_names=[h.name for h in layout.helpers]
    if len(helper_names)!=len(set(helper_names)) or 'forge_contracts' in helper_names:raise ValueError('Helper names must be unique and cannot replace platform types')
    ids={e.id for e in design.api.endpoints};requirements={f'R{i+1}' for i in range(len(brief.acceptance_criteria))}
    for page in layout.pages:
        if not set(page.components)<=set(names) or not set(page.endpoint_ids)<=ids:raise ValueError('Page refers to undeclared components or endpoints')
        if not set(page.requirement_ids)<=requirements:raise ValueError('Page refers to unknown requirement IDs')
    if ids-{operation for page in layout.pages for operation in page.endpoint_ids}:
        raise ValueError('Every business operation must be referenced by an implementing page; otherwise UI builders receive an incomplete operation contract')
    for component in layout.components:
        if len({p.name for p in component.props}|{f.name for f in component.callbacks})!=len(component.props)+len(component.callbacks):raise ValueError('Component prop/callback names must be unique')
        for prop in component.props:check_type(prop.type)
    for functions in [*[c.callbacks for c in layout.components], *[h.functions for h in layout.helpers]]:
        if len({f.name for f in functions})!=len(functions):raise ValueError('Function names must be unique within a module')
        for function in functions:
            check_type(function.returns, void=True)
            if len({p.name for p in function.parameters})!=len(function.parameters):raise ValueError('Parameter names must be unique')
            for parameter in function.parameters:check_type(parameter.type)
    frontend=[f'app/components/{c.name}.tsx' for c in layout.components]+['app/'+(p.path.strip('/')+'/' if p.path!='/' else '')+'page.tsx' for p in layout.pages]
    backend=[f'lib/{h.name}.ts' for h in layout.helpers]+list(dict.fromkeys(e.file for e in design.api.endpoints))
    if len(backend)>10 or len(frontend)>10 or len(frontend)+len(backend)>12:
        raise ValueError(f'Layout exceeds the small-app file budget: {len(frontend)} frontend, {len(backend)} backend. At most 10 per owner and 12 total; consolidate optional components/helpers without removing required behavior.')
    # Display contracts are derived views, never a second model decision.
    front_contract='Authoritative interfaces: design.layout; DTOs: lib/forge_contracts.ts. Pages: '+', '.join(p.path for p in layout.pages)+'. Components: '+', '.join(names)
    back_contract='Authoritative interfaces: design.api and design.layout.helpers; DTOs: lib/forge_contracts.ts. Operations: '+', '.join(e.id for e in design.api.endpoints)
    return ImplementationPlan(spec_version=2, framework='nextjs-app-router', database=brief.database,
        routes=[e.method+' '+e.path for e in design.api.endpoints],
        tasks=[{'owner':'frontend','objective':'Implement the reviewed pages and interactions.','files':frontend,'contract':front_contract},
               {'owner':'backend','objective':'Implement the reviewed operation contracts and data behavior.','files':backend,'contract':back_contract}],
        verification=['Typecheck','Production build','Approved application acceptance',*(['Restart persistence and database integrity'] if brief.database=='sqlite' else [])],design=design)


def render_types(brief, design):
    shapes=all_shapes(brief,design.api)
    rows=['// Controller-rendered interfaces from the approved app design. Do not edit.']
    for shape in shapes.values():
        rows.append(f'export interface {shape.name} {{')
        for field in shape.fields:
            rows.append(f'  {field.name}{"" if field.required else "?"}: {field.type}{" | null" if field.nullable else ""};')
        rows.append('}')
    return '\n'.join(rows)+'\n'


def coding_contract(brief, design, relative):
    """One immutable projection for the assigned file; do not duplicate the whole design."""
    layout=design.layout
    frontend=relative.startswith('app/') and not relative.startswith('app/api/')
    pages=[p for p in layout.pages if relative=='app/'+(p.path.strip('/')+'/' if p.path!='/' else '')+'page.tsx']
    components=[c for c in layout.components if relative==f'app/components/{c.name}.tsx']
    helpers=[h for h in layout.helpers if relative==f'lib/{h.name}.ts']
    if components:pages=[p for p in layout.pages if components[0].name in p.components]
    operations=[e for e in design.api.endpoints if not relative or e.file==relative]
    if pages:
        ids={eid for page in pages for eid in page.endpoint_ids}
        operations=[e for e in design.api.endpoints if e.id in ids]
    if helpers:operations=list(design.api.endpoints)
    return {'version':design.version,'brief_fingerprint':design.brief_fingerprint,
            'design_fingerprint':hashlib.sha256(design.model_dump_json().encode()).hexdigest(),
            'operations':[{**e.model_dump(),'path':e.path,'file':e.file} for e in operations],
            'pages':[p.model_dump() for p in pages],
            'components':[c.model_dump() for c in layout.components if frontend and (not pages or any(c.name in p.components for p in pages))],
            'helpers':[] if frontend else [h.model_dump() for h in layout.helpers],
            'platform_types':{'lib/forge_contracts.ts':render_types(brief,design)}}
