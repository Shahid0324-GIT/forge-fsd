"""Requirements-derived browser contracts stored outside generated workspaces."""
from forge.execution_models import execution_model,authorized_models
import hashlib
import json
from pathlib import Path
from typing import Annotated,Literal

from pydantic import Field,model_validator

from forge.handoffs import record_handoff
from forge.scenario_quality import validate_quality
from forge.acceptance_review import load_quality_review
from forge.tasks import CheckEvidence,Envelope


class TextTarget(Envelope):
    by: Literal['label','text','placeholder']
    value: str = Field(min_length=1,max_length=300)
    name: Literal[''] = ''


class RoleTarget(Envelope):
    by: Literal['role']
    value: Literal['button','link','heading','textbox','spinbutton','checkbox','combobox','option','status','alert',
        'list','listitem','table','row','columnheader','cell','dialog','tab','tabpanel','progressbar','radio',
        'radiogroup','switch','slider','img','main','navigation','region','form','group','searchbox','separator']
    name: str = Field(default='',max_length=300,description='Accessible name; omit only when matching the role alone is unambiguous.')


Target=Annotated[RoleTarget | TextTarget,Field(discriminator='by')]


class Visit(Envelope):
    action: Literal['visit'] = Field(description='Navigate to an app path. Repeated visits in one scenario reload within the same browser session, preserving its storage.')
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


class TextRoleTarget(RoleTarget):
    value: Literal['button','link','heading','option','status','alert','list','listitem','table','row','columnheader','cell',
        'dialog','tab','tabpanel','progressbar','radiogroup','img','main','navigation','region','form','group','separator']


class ValueRoleTarget(RoleTarget):
    value: Literal['textbox','spinbutton','combobox','searchbox']


class Text(Envelope):
    action: Literal['assert_text']
    target: Annotated[TextRoleTarget | TextTarget,Field(discriminator='by')]
    value: str = Field(max_length=600)


class Value(Envelope):
    action: Literal['assert_value']
    target: Annotated[ValueRoleTarget | TextTarget,Field(discriminator='by')]
    value: str = Field(max_length=600)


class Count(Envelope):
    action: Literal['assert_count']
    target: Target
    count: int = Field(ge=0,le=1000)


class Title(Envelope):
    action: Literal['assert_title']
    value: str = Field(min_length=1,max_length=300)


Step=Annotated[Visit | Click | Fill | Toggle | Visible | Text | Value | Count | Title,Field(discriminator='action')]


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


class PartialCoverage(Uncovered):
    coverage: Literal['partial']
    checked_behavior: str = Field(min_length=1,max_length=400,
        description='The specific observable part exercised by scenarios. reason describes the remaining unverified part, not the entire criterion.')


class AcceptanceSuite(Envelope):
    scenarios: list[Scenario] = Field(max_length=6)
    uncovered: list[PartialCoverage | Uncovered] = Field(default_factory=list,max_length=20,
        description='Unverified criteria or remaining parts. Partial entries also need real scenarios and never count as complete coverage.')


def validate_coverage(suite,criterion_count):
    names=[case.id for case in suite.scenarios]
    if len(set(names))!=len(names):raise ValueError('Scenario IDs must be unique')
    covered={index for case in suite.scenarios for index in case.criteria}
    missing=[item.criterion for item in suite.uncovered]
    if len(set(missing))!=len(missing):raise ValueError('Uncovered criterion indices must be unique')
    partial={item.criterion for item in suite.uncovered if isinstance(item,PartialCoverage)}
    overlap=covered.intersection(missing)-partial
    if overlap:raise ValueError(f'Criteria {sorted(overlap)} are both covered and uncovered without an explicit partial coverage declaration. Use coverage=partial and checked_behavior for mixed criteria; preserve real assertions and explain the unverified remainder in reason.')
    if partial-covered:raise ValueError(f'Partial criteria {sorted(partial-covered)} need scenarios exercising checked_behavior; otherwise declare them entirely uncovered.')
    if covered|set(missing)!=set(range(1,criterion_count+1)):
        expected=set(range(1,criterion_count+1));actual=covered|set(missing)
        raise ValueError(f'Every criterion needs a scenario or uncovered reason. Missing: {sorted(expected-actual)}; invalid indices: {sorted(actual-expected)}. Indices are one-based.')


INSTRUCTION='''You are the independent acceptance QA agent. Derive executable browser
checks from the original request, human answers/feedback and APPROVED design. You
receive no generated implementation or builder diagnosis. Never weaken requirements
to accommodate an implementation. Choose accessible semantic targets and concrete
assertions. Original requirements and explicit exclusions outrank contradictory design
assumptions: mark a conflicting criterion uncovered with its conflict, never test it as
the desired behavior. 'No saved data' means no persistence across reloads, including
browser storage as well as a database. Choose concrete
inputs/expected results, not CSS selectors or JavaScript. The builder will receive
this frozen contract so it can provide appropriate accessible controls.
Use a few concise scenarios with actual assertions. Each scenario starts at visit /
or another approved app route in a fresh session. Use role/button/name for controls,
label for labelled inputs, text for visible content, and assert_value for input values.
Missing markup/style details are not unsupported capabilities: choose suitable semantic
targets from the approved behavior. Builders can align accessible controls during repair.
One assertion may cover multiple criteria; a visible value assertion can also prove a
display requirement. Mark uncovered only for genuinely unavailable checks or conflicts,
not because the design leaves routine UI implementation choices to the builder.
Each NEW SCENARIO gets a fresh app process, temporary database and browser session.
Scenarios cannot rely on data created by another scenario. A second visit / within one
scenario reloads while preserving that session's storage; use it for reload and
no-saved-state checks. Do not mark reload behavior unsupported.
Observe the changed state BEFORE a reload and the required result immediately AFTER
it. Never clear/reset to the initial state first: that cannot distinguish persistence
from reset. Assertions before an interaction do not verify the interaction's result.
State exact expected numbers/text from the requirements. Exercise repeated actions,
invalid input and state transitions when applicable. Reference all approved criteria
using one-based indices. If a criterion cannot be demonstrated with these browser
actions, mark it uncovered with a factual reason; do not substitute a superficial
check or claim that a database restart, security or deployment was verified.
Tests execute only after source generation/build. Return a test contract, not code,
private reasoning or claims of execution. Correct reported protocol errors without
dropping assertions or requested functionality.
For a criterion combining supported and unsupported checks, keep its executable part
in scenarios and add an uncovered entry with coverage="partial", checked_behavior
describing exactly what those scenarios check, and reason describing the unverified
remainder. Do not drop valid checks or pretend the whole criterion is verified.
Entirely unsupported criteria use ordinary uncovered entries without coverage or
checked_behavior. Neither kind of uncovered entry permits a complete-success claim.'''


def suite_path(ledger,state):
    return ledger.store.path.parent/'acceptance-plans'/ledger.job_id/f'suite-{state.task.id}-r{state.revision}.json'


def suite_fingerprint(ledger,state):
    path=suite_path(ledger,state)
    return hashlib.sha256(path.read_bytes() if path.is_file() else b'').hexdigest()


def proposal_context(ledger,state,review):
    directory=suite_path(ledger,state).parent
    proposals=list(directory.glob(f'proposal-{state.task.id}-r{state.revision}-a*.json'))
    previous=None
    if proposals:
        path=max(proposals,key=lambda item:int(item.stem.rsplit('-a',1)[1]))
        if path.stat().st_size>100000:raise ValueError('QA proposal exceeds context budget')
        previous=json.loads(path.read_text(encoding='utf-8'))
    else:
        # Recover a pre-proposal-persistence trial using its controller invocation trace.
        call=next((e['payload'] for e in reversed(ledger.store.read(ledger.job_id)['events'])
            if e['status']=='AGENT_CALL_COMPLETED' and e['payload'].get('schema')=='AcceptanceSuite'
            and e['payload'].get('task_id')==state.task.id and e['payload'].get('report')),None)
        if call:
            path=Path(call['report']).resolve()
            if path.is_relative_to(ledger.store.path.parent.resolve()) and path.stat().st_size<=160000:
                trace=json.loads(path.read_text(encoding='utf-8'))
                if trace.get('job_id')==ledger.job_id and not trace.get('output_truncated'):
                    try:previous=AcceptanceSuite.model_validate_json(trace['output']).model_dump()
                    except (ValueError,KeyError):pass
    # Independent behavior QA needs the agreed design/criteria, not source-file
    # assignments or an earlier model's proposed test implementation. Preserve
    # their hashes and the complete approved snapshot outside this prompt.
    design={key:value for key,value in review['draft'].items() if key not in {'files','test_strategy'}}
    omitted={key:hashlib.sha256(json.dumps(review['draft'][key],sort_keys=True).encode()).hexdigest()
        for key in ('files','test_strategy') if key in review['draft']}
    data={**review['binding']['inputs'],'approved_design':design,'approved_design_omitted':omitted,'review_fingerprint':review['fingerprint'],
        'previous_proposal':previous,'protocol_errors':[o.error for o in state.observations[-2:] if o.error],
        'browser_protocol_constraints':{'unsupported':['CSS/XPath selectors','attribute assertions','keyboard actions',
            'storage/cookie inspection','screen-reader execution'],
            'scope':'Use the actual response schema. Prior model suggestions cannot add capabilities; retain genuinely unsupported criteria as uncovered.'},
        'correction_instruction':'Correct the precise protocol errors in the previous proposal. Return the complete contract without dropping valid assertions.'}
    if state.recovery and state.reviewed_observations==len(state.observations):data['fresh_review']=state.recovery.model_dump()
    if len(json.dumps(data,separators=(',',':')))>22000:raise ValueError('QA context exceeds budget; split the verification scope rather than dropping requirements')
    return data


def acceptance_worker(ledger,state,agents,review,authorize,review_coverage=None,review_quality=None):
    authorize();ledger.assert_active(state)
    if state.task.owner!='qa' or state.task.inputs.get('review_fingerprint')!=review['fingerprint']:
        raise ValueError('QA task must belong to the approved review')
    if agents.model_name!=execution_model(ledger.job_id,ledger.store,review):raise ValueError('Use the approved model for acceptance QA')
    data=proposal_context(ledger,state,review)
    previous_context=getattr(agents,'invocation_context',{});previous_activity=getattr(agents,'activity',None)
    if getattr(agents,'trace_directory',None) is None:agents.trace_directory=ledger.store.path.parent/'model-calls'/ledger.job_id
    try:
        record_handoff(ledger.store,ledger.job_id,'coordinator','acceptance_qa',
            'Define independent assertions from approved requirements; no app source is supplied.',data,
            agents=agents,task_id=state.task.id,parent_task_id=state.task.parent_id,task_state=state)
        agents.activity=lambda status,payload:ledger.store.event(ledger.job_id,status,payload,update_status=False)
        suite=AcceptanceSuite.model_validate(agents.generate(AcceptanceSuite,INSTRUCTION,data,coding=True))
        authorize();ledger.assert_active(state)
        proposal=suite_path(ledger,state).parent/f'proposal-{state.task.id}-r{state.revision}-a{state.actions_used}.json'
        proposal.parent.mkdir(parents=True,exist_ok=True)
        with proposal.open('x',encoding='utf-8',newline='\n') as output:output.write(suite.model_dump_json(indent=2))
        validate_coverage(suite,len(review['draft']['acceptance_criteria']))
        validate_quality(suite.model_dump())
        if suite.uncovered and review_coverage:review_coverage(suite)
        quality=review_quality(suite) if review_quality else None
        if review_quality:
            if not quality:raise ValueError('Scenario reviewer must return bound review evidence')
            if load_quality_review(ledger,state,review,suite.model_dump(),quality).issues:
                raise ValueError('Scenario review still has unresolved findings')
        authorize();ledger.assert_active(state)
        packet={'version':1,'job_id':ledger.job_id,'task_id':state.task.id,'revision':state.revision,
            'scenario_quality_version':1,
            'quality_review':quality,
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
        or packet.get('model') not in authorized_models(ledger.job_id,ledger.store,review)):raise ValueError('Acceptance contract belongs to another review/task/model')
    suite=AcceptanceSuite.model_validate(packet['suite']);validate_coverage(suite,len(review['draft']['acceptance_criteria']))
    if packet.get('scenario_quality_version') is not None:
        if packet['scenario_quality_version']!=1:raise ValueError('Unknown scenario-quality protocol')
        validate_quality(suite.model_dump())
    if packet.get('quality_review') is not None:
        if load_quality_review(ledger,state,review,suite.model_dump(),packet['quality_review']).issues:
            raise ValueError('Frozen contract has unresolved scenario-review findings')
    return {**packet,'fingerprint':digest,'report':str(path.resolve())}
