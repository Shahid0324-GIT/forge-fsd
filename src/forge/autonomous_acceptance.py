"""Requirements-derived browser contracts stored outside generated workspaces."""
import hashlib
import json
from pathlib import Path
from typing import Annotated,Literal

from pydantic import Field,model_validator

from forge.handoffs import record_handoff
from forge.tasks import CheckEvidence,Envelope


class Target(Envelope):
    by: Literal['role','label','text','placeholder']
    value: str = Field(min_length=1,max_length=300)
    name: str = Field(default='',max_length=300,description='Accessible name for role targets only; empty otherwise.')

    @model_validator(mode='after')
    def role_name(self):
        if self.by!='role' and self.name:raise ValueError('Only role targets use name')
        return self


class Visit(Envelope):
    action: Literal['visit']
    path: str = Field(default='/',pattern=r'^/(?:[a-zA-Z0-9_?&=.%+~\-][a-zA-Z0-9/_?&=.%+~\-]*)?$',max_length=300)


class Click(Envelope):
    action: Literal['click']
    target: Target


class Fill(Envelope):
    action: Literal['fill','select']
    target: Target
    value: str = Field(max_length=600)


class Toggle(Envelope):
    action: Literal['check']
    target: Target
    checked: bool


class Visible(Envelope):
    action: Literal['assert_visible']
    target: Target


class Text(Envelope):
    action: Literal['assert_text','assert_value']
    target: Target
    value: str = Field(max_length=600)


class Count(Envelope):
    action: Literal['assert_count']
    target: Target
    count: int = Field(ge=0,le=1000)


class Title(Envelope):
    action: Literal['assert_title']
    value: str = Field(min_length=1,max_length=300)


Step=Annotated[Visit | Click | Fill | Toggle | Visible | Text | Count | Title,Field(discriminator='action')]


class Scenario(Envelope):
    id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,47}$')
    criteria: list[int] = Field(min_length=1,max_length=20,description='One-based indices from the supplied approved acceptance criteria.')
    steps: list[Step] = Field(min_length=2,max_length=16)

    @model_validator(mode='after')
    def executable(self):
        if self.steps[0].action!='visit':raise ValueError('Each scenario starts with visit; scenarios have independent browser sessions')
        if not any(step.action.startswith('assert_') for step in self.steps):raise ValueError('A scenario needs an actual assertion')
        if len(set(self.criteria))!=len(self.criteria):raise ValueError('Scenario criterion indices must be unique')
        return self


class Uncovered(Envelope):
    criterion: int
    reason: str = Field(min_length=1,max_length=400)


class AcceptanceSuite(Envelope):
    scenarios: list[Scenario] = Field(max_length=6)
    uncovered: list[Uncovered] = Field(default_factory=list,max_length=20)


def validate_coverage(suite,criterion_count):
    names=[case.id for case in suite.scenarios]
    if len(set(names))!=len(names):raise ValueError('Scenario IDs must be unique')
    covered={index for case in suite.scenarios for index in case.criteria}
    missing=[item.criterion for item in suite.uncovered]
    if len(set(missing))!=len(missing) or covered.intersection(missing):raise ValueError('A criterion cannot be both covered and uncovered')
    if covered|set(missing)!=set(range(1,criterion_count+1)):
        raise ValueError('Every approved criterion must be referenced by a scenario or explicitly marked uncovered; indices are one-based')


INSTRUCTION='''You are the independent acceptance QA agent. Derive executable browser
checks from the original request, human answers/feedback and APPROVED design. You
receive no generated implementation or builder diagnosis. Never weaken requirements
to accommodate an implementation. Choose accessible semantic targets and concrete
inputs/expected results, not CSS selectors or JavaScript. The builder will receive
this frozen contract so it can provide appropriate accessible controls.
Use a few concise scenarios with actual assertions. Each scenario starts at visit /
or another approved app route in a fresh session. Use role/button/name for controls,
label for labelled inputs, text for visible content, and assert_value for input values.
State exact expected numbers/text from the requirements. Exercise repeated actions,
invalid input and state transitions when applicable. Reference all approved criteria
using one-based indices. If a criterion cannot be demonstrated with these browser
actions, mark it uncovered with a factual reason; do not substitute a superficial
check or claim that a database restart, security or deployment was verified.
Tests execute only after source generation/build. Return a test contract, not code,
private reasoning or claims of execution. Correct reported protocol errors without
dropping assertions or requested functionality.'''


def suite_path(ledger,state):
    return ledger.store.path.parent/'acceptance-plans'/ledger.job_id/f'suite-{state.task.id}-r{state.revision}.json'


def suite_fingerprint(ledger,state):
    path=suite_path(ledger,state)
    return hashlib.sha256(path.read_bytes() if path.is_file() else b'').hexdigest()


def acceptance_worker(ledger,state,agents,review,authorize):
    authorize();ledger.assert_active(state)
    if state.task.owner!='qa' or state.task.inputs.get('review_fingerprint')!=review['fingerprint']:
        raise ValueError('QA task must belong to the approved review')
    if agents.model_name!=review['binding']['model']:raise ValueError('Use the approved model for acceptance QA')
    data={**review['binding']['inputs'],'approved_design':review['draft'],
        'review_fingerprint':review['fingerprint'],
        'protocol_errors':[o.error for o in state.observations[-2:] if o.error]}
    previous_context=getattr(agents,'invocation_context',{});previous_activity=getattr(agents,'activity',None)
    if getattr(agents,'trace_directory',None) is None:agents.trace_directory=ledger.store.path.parent/'model-calls'/ledger.job_id
    try:
        record_handoff(ledger.store,ledger.job_id,'coordinator','acceptance_qa',
            'Define independent assertions from approved requirements; no app source is supplied.',data,
            agents=agents,task_id=state.task.id,parent_task_id=state.task.parent_id)
        agents.activity=lambda status,payload:ledger.store.event(ledger.job_id,status,payload,update_status=False)
        suite=AcceptanceSuite.model_validate(agents.generate(AcceptanceSuite,INSTRUCTION,data,coding=True))
        validate_coverage(suite,len(review['draft']['acceptance_criteria']))
        authorize();ledger.assert_active(state)
        packet={'version':1,'job_id':ledger.job_id,'task_id':state.task.id,'revision':state.revision,
            'review_fingerprint':review['fingerprint'],'model':agents.model_name,'suite':suite.model_dump(),
            'scope':'Requirements-derived assertions; coverage references are QA proposals, not execution evidence.'}
        path=suite_path(ledger,state);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf-8',newline='\n') as output:output.write(json.dumps(packet,indent=2))
        return [CheckEvidence(check='acceptance_contract',exit_code=0,fingerprint=suite_fingerprint(ledger,state),
            report=str(path.resolve()),summary='Independent test contract frozen; no application tests have executed.')]
    finally:agents.invocation_context=previous_context;agents.activity=previous_activity


def load_acceptance(ledger,state,review):
    current=ledger.read(state.task.id)
    if current.version!=state.version or current.revision!=state.revision:raise ValueError('Acceptance task changed; retrieve its current evidence')
    if state.status!='completed' or state.task.owner!='qa':raise ValueError('Acceptance contract requires a completed independent QA task')
    path=suite_path(ledger,state)
    if path.stat().st_size>100000:raise ValueError('Acceptance contract exceeds the artifact budget')
    raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
    observation=state.observations[-1]
    if observation.fingerprint!=digest or ledger.failures(state,observation):raise ValueError('Acceptance contract changed or lacks passing protocol evidence')
    if not any(c.check=='acceptance_contract' and Path(c.report).resolve()==path.resolve() for c in observation.checks):
        raise ValueError('Acceptance contract report does not match its task')
    packet=json.loads(raw)
    if (packet.get('version')!=1 or packet.get('job_id')!=ledger.job_id or packet.get('task_id')!=state.task.id
        or packet.get('revision')!=state.revision or packet.get('review_fingerprint')!=review['fingerprint']
        or packet.get('model')!=review['binding']['model']):raise ValueError('Acceptance contract belongs to another review/task/model')
    suite=AcceptanceSuite.model_validate(packet['suite']);validate_coverage(suite,len(review['draft']['acceptance_criteria']))
    return {**packet,'fingerprint':digest,'report':str(path.resolve())}
