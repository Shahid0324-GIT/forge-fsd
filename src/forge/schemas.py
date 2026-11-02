import json
import re
from typing import Literal,Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator,JsonValue
from forge.models import LocalModel,DEFAULT_MODEL
from forge.contracts import DataContract, AppDesign


class Boundary(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArchitectureReview(Boundary):
    issues: list[Annotated[str,Field(min_length=1,max_length=600)]] = Field(max_length=6)


class AcceptanceReview(Boundary):
    issues: list[Annotated[str,Field(min_length=1,max_length=600)]] = Field(max_length=6)


class ApplicationRequest(Boundary):
    description: str = Field(min_length=10, max_length=4000)
    model: LocalModel = DEFAULT_MODEL


class AppField(Boundary):
    name: str = Field(pattern=r'^[a-z][a-z0-9_]{0,31}$')
    kind: Literal['text','number','boolean','date','enum','reference']
    required: bool
    constraints: str = Field(max_length=300)


class AppEntity(Boundary):
    name: str = Field(pattern=r'^[a-z][a-z0-9_]{0,31}$')
    fields: list[AppField] = Field(min_length=1,max_length=8)
    relationships: str = Field(max_length=500)


class CaptureBinding(Boundary):
    pointer: str = Field(min_length=1,max_length=100,pattern=r'^/')
    capture: str = Field(pattern=r'^[a-z][a-z0-9_]{0,31}$')


class AcceptanceStep(Boundary):
    method: Literal['GET','POST','PUT','PATCH','DELETE']
    path: str = Field(min_length=1,max_length=200)
    body_json: str = Field(default='',max_length=3000)
    status: int = Field(ge=200,le=499)
    expect_json: str = Field(default='',max_length=3000)
    contains: str = Field(default='',max_length=300)
    save_as: str = Field(default='',pattern=r'^(?:[a-z][a-z0-9_]{0,31})?$')
    save_pointer: str = Field(default='',max_length=100)
    body_bindings: list[CaptureBinding] = Field(default_factory=list,max_length=8)
    expect_bindings: list[CaptureBinding] = Field(default_factory=list,max_length=8)

    @model_validator(mode='after')
    def validate_request(self):
        if not re.fullmatch(r'/[a-zA-Z0-9_/{},?.=&%+\-]*',self.path) or '//' in self.path or '..' in self.path:
            raise ValueError('Acceptance requests must use local relative paths')
        for value in (self.body_json,self.expect_json):
            if value:json.loads(value)
        for raw,bindings in [(self.body_json,self.body_bindings),(self.expect_json,self.expect_bindings)]:
            if bindings and not raw:raise ValueError('Capture bindings require a JSON fixture')
            for binding in bindings:
                target=json.loads(raw)
                for part in binding.pointer.split('/')[1:]:
                    part=part.replace('~1','/').replace('~0','~')
                    if isinstance(target,list) and part.isdigit() and int(part)<len(target):target=target[int(part)]
                    elif isinstance(target,dict) and part in target:target=target[part]
                    else:raise ValueError('Capture binding must point to an existing JSON fixture value')
        if self.save_pointer and not self.save_pointer.startswith('/'):
            raise ValueError('Capture pointer must be a JSON pointer')
        if self.save_as and not self.save_pointer:
            raise ValueError('save_as requires a scalar JSON pointer such as /id; otherwise leave both capture fields empty')
        if self.method=='GET' and self.body_json:raise ValueError('GET requests cannot have a body')
        if self.method in {'POST','PUT','PATCH'} and self.status<400 and not self.body_json:
            raise ValueError('Successful mutation tests need an explicit JSON input fixture; use {} only for a bodyless action')
        return self


def validate_app_contract(requirements,plan):
    if requirements.spec_version!=plan.spec_version:
        raise ValueError('Requirements and plan versions must match')
    if requirements.spec_version==1:return
    if requirements.database!=plan.database:raise ValueError('Database choice differs from requirements')
    if requirements.data_contract is not None and plan.design is None:
        raise ValueError('Typed business requirements need their authoritative typed app design')
    if plan.design is not None:
        from forge.contracts import compile_design
        brief=AppBrief.model_validate({key:value for key,value in requirements.model_dump().items() if key in AppBrief.model_fields})
        expected=compile_design(brief,plan.design)
        if expected.model_dump()!=plan.model_dump():
            raise ValueError('Execution plan differs from its authoritative typed design')
    files={file for task in plan.tasks for file in task.files}
    for page in requirements.pages:
        path='app/'+(page.strip('/')+'/' if page!='/' else '')+'page.tsx'
        if path not in files:raise ValueError('Each approved page needs a frontend file')
    for route in plan.routes:
        _,path=route.split(' ',1)
        target='app'+re.sub(r'\{([a-zA-Z0-9_]+)\}',r'[\1]',path)+'/route.ts'
        if target not in files:raise ValueError('Each API route needs a backend file')
    for scenario in getattr(requirements,'scenarios',[]):
        for step in scenario.steps:
            path=re.sub(r'\{\{[a-z][a-z0-9_]*\}\}','probe',step.path.split('?')[0])
            if path in requirements.pages and step.method=='GET':
                if step.expect_json or step.save_as:raise ValueError('Page responses are HTML, not JSON')
                continue
            if not any(method==step.method and re.fullmatch(re.sub(r'\{[a-zA-Z0-9_]+\}',r'[^/]+',route),path) for method,route in (r.split(' ',1) for r in plan.routes)):
                raise ValueError('Acceptance request is missing from the approved API contract')


class AcceptanceScenario(Boundary):
    name: str = Field(min_length=1,max_length=100)
    phase: Literal['functional','restart']
    steps: list[AcceptanceStep] = Field(min_length=1,max_length=8)


def validate_small_app(document):
    if not document.pages or '/' not in document.pages or len(set(document.pages))!=len(document.pages):
        raise ValueError('Small apps need unique pages including /')
    if any(p=='/api' or p.startswith('/api/') or not re.fullmatch(r'/(?:[a-z][a-z0-9-]*(?:/[a-z][a-z0-9-]*)*)?',p) for p in document.pages):
        raise ValueError('Pages must be HTML routes; API endpoints do not belong in pages')
    if document.database=='sqlite' and not document.entities:
        raise ValueError('Database apps need an entity specification')
    if len({e.name for e in document.entities})!=len(document.entities) or any(len({f.name for f in e.fields})!=len(e.fields) for e in document.entities):
        raise ValueError('Entity and field names must be unique')


def validate_scenarios(scenarios,database):
    functional=[s for s in scenarios if s.phase=='functional']
    if len(functional)<2 or not any(step.status>=400 for s in functional for step in s.steps):
        raise ValueError('Include functional and invalid-input acceptance scenarios')
    if not any(step.expect_json or step.contains for s in functional for step in s.steps):
        raise ValueError('Acceptance must assert application behavior, not status alone')
    if sum(len(s.steps) for s in scenarios)>40:raise ValueError('Acceptance request budget exceeded')
    if database=='sqlite':
        restart=[step for s in scenarios if s.phase=='restart' for step in s.steps]
        if not any(step.method=='GET' and step.status==200 and step.path.startswith('/api/') and step.expect_json and json.loads(step.expect_json) for step in restart):
            raise ValueError('SQLite apps require a restart persistence scenario asserting stored JSON data')
        if not any(step.method in {'POST','PUT','PATCH'} and step.status<400 for s in functional for step in s.steps):
            raise ValueError('Persistence checks must create data before restarting')
    captures=set()
    for phase in ('functional','restart'):
        for scenario in (s for s in scenarios if s.phase==phase):
            for step in scenario.steps:
                for value in (step.path,step.body_json,step.expect_json,step.contains):
                    for name in re.findall(r'\{\{([a-z][a-z0-9_]*)\}\}',value):
                        if name not in captures:raise ValueError(f'Acceptance capture {name} is used before it is saved')
                for binding in [*step.body_bindings,*step.expect_bindings]:
                    if binding.capture not in captures:raise ValueError(f'Acceptance capture {binding.capture} is used before it is saved')
                if step.save_as:captures.add(step.save_as)
    # Recognize an explicit captured CRUD lifecycle, not arbitrary application logic.
    # An uncaptured create makes the collection's final contents unknown to this check.
    records={};unknown=set()
    for scenario in functional:
        for step in scenario.steps:
            if step.status>=300:continue
            if step.method=='POST':
                if step.save_as and step.save_pointer=='/id':
                    if step.save_as in records:unknown.add(records[step.save_as][0])
                    records[step.save_as]=[step.path,True]
                else:unknown.add(step.path)
            match=re.fullmatch(r'(.+)/\{\{([a-z][a-z0-9_]*)\}\}',step.path)
            if match and match[2] in records and records[match[2]][0]==match[1]:
                if step.method=='DELETE':records[match[2]][1]=False
                elif step.method in {'PUT','PATCH'} and step.status==201:records[match[2]][1]=True
    if database=='sqlite':
        for scenario in scenarios:
            if scenario.phase!='restart':continue
            for step in scenario.steps:
                known=[alive for collection,alive in records.values() if collection==step.path]
                if (step.method=='GET' and step.status==200 and step.expect_json and json.loads(step.expect_json)
                        and known and not any(known) and step.path not in unknown):
                    raise ValueError(f'Restart fixture for {step.path} expects stored records after all its captured records were deleted; create and retain a separate fixture')


class AppBrief(Boundary):
    spec_version: Literal[2]
    title: str = Field(min_length=1,max_length=160)
    acceptance_criteria: list[str] = Field(min_length=4,max_length=15)
    assumptions: list[str] = Field(max_length=8)
    open_questions: list[str] = Field(max_length=3)
    database: Literal['sqlite','none']
    entities: list[AppEntity] = Field(max_length=3)
    pages: list[str] = Field(min_length=1,max_length=5)
    data_contract: DataContract | None = None

    @model_validator(mode='after')
    def validate_scope(self):
        validate_small_app(self)
        return self


class AppAcceptancePlan(Boundary):
    database: Literal['sqlite','none']
    scenarios: list[AcceptanceScenario] = Field(min_length=2,max_length=10)

    @model_validator(mode='after')
    def validate_tests(self):
        validate_scenarios(self.scenarios,self.database)
        return self


class NativeAcceptanceStep(Boundary):
    method: Literal['GET','POST','PUT','PATCH','DELETE']
    path: str = Field(min_length=1,max_length=200)
    body: JsonValue
    status: int = Field(ge=200,le=499)
    expected: JsonValue
    contains: str = Field(default='',max_length=300)
    save_as: str = Field(default='',pattern=r'^(?:[a-z][a-z0-9_]{0,31})?$')
    save_pointer: str = Field(default='',max_length=100)
    body_bindings: list[CaptureBinding] = Field(default_factory=list,max_length=8)
    expect_bindings: list[CaptureBinding] = Field(default_factory=list,max_length=8)

    def to_step(self):
        return AcceptanceStep.model_validate({
            **self.model_dump(exclude={'body','expected'}),
            'body_json':json.dumps(self.body,separators=(',',':')) if self.body is not None else '',
            'expect_json':json.dumps(self.expected,separators=(',',':')) if self.expected is not None else ''})


class NativeAcceptanceScenario(Boundary):
    name: str = Field(min_length=1,max_length=100)
    phase: Literal['functional','restart']
    steps: list[NativeAcceptanceStep] = Field(min_length=1,max_length=8)


class NativeAcceptancePlan(Boundary):
    database: Literal['sqlite','none']
    scenarios: list[NativeAcceptanceScenario] = Field(min_length=2,max_length=10)

    def to_plan(self):
        return AppAcceptancePlan(database=self.database,scenarios=[AcceptanceScenario(
            name=scenario.name,phase=scenario.phase,steps=[step.to_step() for step in scenario.steps]) for scenario in self.scenarios])

    @model_validator(mode='after')
    def validate_plan(self):
        self.to_plan()
        return self


class RequirementsDocument(Boundary):
    spec_version: Literal[1,2] = 1
    title: str = Field(min_length=1, max_length=160)
    entity: str = Field(default='',max_length=40)
    fields: list[str] = Field(default_factory=list,max_length=10)
    operations: list[Literal["create", "read", "update", "delete"]] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(min_length=4, max_length=15)
    assumptions: list[str] = Field(max_length=8)
    open_questions: list[str] = Field(max_length=3)
    database: Literal['sqlite','none'] = 'sqlite'
    entities: list[AppEntity] = Field(default_factory=list,max_length=3)
    pages: list[str] = Field(default_factory=list,max_length=5)
    scenarios: list[AcceptanceScenario] = Field(default_factory=list,max_length=10)
    data_contract: DataContract | None = None

    @model_validator(mode="after")
    def require_crud(self):
        if self.spec_version==2:
            validate_small_app(self)
            if not self.open_questions:validate_scenarios(self.scenarios,self.database)
            return self
        if self.entity!='task':raise ValueError('Legacy specification requires task entity')
        if set(self.operations) != {"create", "read", "update", "delete"}:
            raise ValueError("All four CRUD operations are required")
        if not {"title", "description", "status"}.issubset(set(self.fields)):
            raise ValueError("Required task fields are missing")
        return self


class ImplementationTask(Boundary):
    owner: Literal["frontend", "backend"]
    objective: str = Field(min_length=1, max_length=1000)
    files: list[str] = Field(min_length=1, max_length=10)
    contract: str = Field(default='',max_length=3000)


class ImplementationPlan(Boundary):
    spec_version: Literal[1,2] = 1
    framework: Literal["nextjs-app-router"]
    database: Literal['sqlite','none']
    routes: list[Annotated[str,Field(pattern=r'^(GET|POST|PUT|PATCH|DELETE) /api/[a-zA-Z0-9_/{}/-]+$')]] = Field(min_length=1,max_length=15)
    tasks: list[ImplementationTask] = Field(min_length=2, max_length=6)
    verification: list[str] = Field(min_length=3, max_length=10)
    design: AppDesign | None = None

    @model_validator(mode="after")
    def check_contract(self):
        expected = {"GET /api/tasks", "POST /api/tasks", "GET /api/tasks/{id}",
                    "PATCH /api/tasks/{id}", "DELETE /api/tasks/{id}"}
        if self.spec_version==1 and (set(self.routes) != expected or len(self.routes)!=5 or self.database!='sqlite'):
            raise ValueError("Plan must preserve the supported CRUD API contract")
        if self.spec_version==2 and (len(set(self.routes))!=len(self.routes) or any(not re.fullmatch(r'(?:GET|POST|PUT|PATCH|DELETE) /api/[a-zA-Z0-9_/{}/-]+',r) for r in self.routes)):
            raise ValueError('Plan requires unique local API routes with HTTP methods')
        if {task.owner for task in self.tasks} != {"frontend", "backend"}:
            raise ValueError("Plan must delegate to frontend and backend")
        owners = {}
        for task in self.tasks:
            for file in task.files:
                # Planning validation only: execution will also need resolved-path checks.
                if not file or file.startswith(("/", "\\")) or "\\" in file or ":" in file or any(p in {"", ".", ".."} for p in file.split("/")):
                    raise ValueError("File manifest requires clean relative POSIX paths")
                if not file.endswith((".ts", ".tsx")) or file.startswith("pages/"):
                    raise ValueError("This template requires TypeScript and App Router paths")
                backend_path = file.startswith(("app/api/", "lib/"))
                if backend_path != (task.owner == "backend"):
                    raise ValueError("API and lib files belong to backend; UI files belong to frontend")
                if file in owners and owners[file] != task.owner:
                    raise ValueError("Conflicting file ownership")
                owners[file] = task.owner
                if self.spec_version==2:
                    if file in {'app/layout.tsx','app/api/health/route.ts'} or not re.fullmatch(r'(?:app|lib)/(?:[a-zA-Z0-9_\[\]-]+/)*[a-zA-Z0-9_-]+\.tsx?',file):
                        raise ValueError('File is outside editable app/lib source')
        if self.spec_version==2:
            if len({file.casefold() for file in owners})!=len(owners):
                raise ValueError('File paths collide on case-insensitive filesystems')
            if len(owners)>12 or 'app/page.tsx' not in owners:
                raise ValueError('Small apps need a home page and at most twelve source files')
            if any(not task.contract for task in self.tasks):raise ValueError('Builders need explicit interface contracts')
        return self


class AppRequirements(RequirementsDocument):
    spec_version: Literal[2] = Field(...)


class FrontendTask(ImplementationTask):
    owner: Literal['frontend']


class BackendTask(ImplementationTask):
    owner: Literal['backend']


class AppImplementationPlan(ImplementationPlan):
    spec_version: Literal[2] = Field(...)
    tasks: tuple[FrontendTask,BackendTask]
