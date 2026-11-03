"""Independent review of a proposed test suite, bound to that exact proposal."""
import hashlib
import json
from typing import Annotated,Literal

from pydantic import Field

from forge.handoffs import record_handoff
from forge.tasks import CheckEvidence,Envelope,Observation,Task


class TestIssue(Envelope):
    criterion: int = Field(ge=1)
    scenario: str = Field(pattern=r'^[a-z][a-z0-9_]{0,47}$')
    reason: str = Field(min_length=1,max_length=500)
    correction: str = Field(min_length=1,max_length=600)


class AcceptanceCritique(Envelope):
    assessed_criteria: list[int] = Field(max_length=20)
    issues: list[TestIssue] = Field(max_length=8)
    suggestions: list[str] = Field(default_factory=list,max_length=4,description='Optional extra coverage outside explicit requirements; never blocks contract freezing.')


class ScopeFinding(Envelope):
    issue: int = Field(ge=0)
    reason: str = Field(min_length=1,max_length=500)


class RequiredScopeFinding(ScopeFinding):
    classification: Literal['required_behavior']
    requirement_quote: str = Field(min_length=1,max_length=1000)


class OptionalScopeFinding(ScopeFinding):
    classification: Literal['optional_coverage']
    requirement_quote: Literal[''] = ''


class ScopeAssessment(Envelope):
    findings: list[Annotated[RequiredScopeFinding | OptionalScopeFinding,Field(discriminator='classification')]] = Field(max_length=8)


SCOPE_INSTRUCTION='''You are the requirements scope reviewer, not a general QA critic.
For every proposed blocking issue, decide whether its demanded behavior follows from
the actual approved criterion or explicit user requirements. Do not invent robustness
requirements. Adding two valid numbers does not require a non-numeric-input error UI
unless validation was requested. Missing the requested Add interaction or sum assertion
does prevent testing the addition requirement and IS required. Optional edge coverage
belongs in suggestions, not blocking requirements. Scope review does not assess app
source or excuse missing requested functionality. Return one finding per zero-based
issue index. classification=required_behavior needs an exact relevant requirement
quote from the provided requirements/criteria/feedback. classification=optional_coverage
means the finding exceeds the agreed scope and cannot block QA. For optional findings explain that they exceed
the agreed scope. Never claim execution, app correctness or human approval.'''


INSTRUCTION='''You independently review proposed acceptance scenarios, not app source.
For EACH covered criterion, ask what plausible broken app could still pass these steps.
Check the requested trigger, a concrete meaningful input, the expected result, and
whether assertions actually distinguish correct behavior from that broken behavior.
Baseline-only checks cannot prove interactions. Reload checks need an observed changed
state before reloading and an immediate observation afterward; clearing first hides
persistence bugs. Repeated actions, rejected inputs, edits/deletes and derived totals
need corresponding observable effects when requested. Do not require unrelated features
or specific styling, types or file structure. Preserve requested behavior and negative
constraints. Critique only covered criteria; uncovered capabilities are reviewed separately.
issues are BLOCKING omissions of explicitly requested or approved behavior. Do not turn
optional robustness ideas into new requirements. In particular, invalid-input rejection
is blocking only when the request or approved criteria requires it; do not invent error
messages, validation behavior or support for additional input types. Put optional edge
cases and broader coverage in suggestions. Suggestions never block this bounded POC.
Browser UI behavior alone cannot prove internal database technology, absence of all
storage, database integrity, a server restart, security or deployment. If such a claim
is assigned browser-only coverage, request an uncovered limitation or appropriate
separate evidence instead of approving a superficial assertion.
Return assessed_criteria containing exactly the covered indices. Return issues with
existing criterion/scenario references and concrete corrections; issues=[] only when
you find no material gaps against the actual agreed scope. Do not rewrite tests or claim execution,
application correctness or human approval. This review is advisory model judgment,
not a semantic proof. Return concise findings, not private reasoning.'''


def proposal_hash(suite):
    return hashlib.sha256(json.dumps(suite,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _validate(decision,suite):
    cases={case['id']:set(case['criteria']) for case in suite['scenarios']}
    covered={index for indices in cases.values() for index in indices}
    if set(decision.assessed_criteria)!=covered or len(set(decision.assessed_criteria))!=len(decision.assessed_criteria):
        raise ValueError('Quality review must assess every covered criterion exactly once')
    if any(issue.scenario not in cases or issue.criterion not in cases[issue.scenario] for issue in decision.issues):
        raise ValueError('Quality findings must reference a scenario covering that criterion')


def _path(ledger,state,digest):
    return ledger.store.path.parent/'acceptance-plans'/ledger.job_id/f'quality-v2-{state.task.id}-r{state.revision}-{digest}.json'


def _scoped_decision(original,assessment,review):
    indices=[item.issue for item in assessment.findings]
    if len(set(indices))!=len(indices) or set(indices)!=set(range(len(original.issues))):
        raise ValueError('Scope review must classify every proposed blocker exactly once')
    texts=[*review['draft']['acceptance_criteria'],review['binding']['inputs']['original_request'],
        *review['binding']['inputs'].get('human_review_feedback',[]),
        json.dumps(review['binding']['inputs'].get('human_clarifications',[]),ensure_ascii=False)]
    required=[];optional=[]
    for item in assessment.findings:
        issue=original.issues[item.issue]
        if item.classification=='required_behavior':
            if not item.requirement_quote.strip() or not any(item.requirement_quote.casefold() in text.casefold() for text in texts):
                raise ValueError('A blocking quality finding requires a quote from the agreed requirements')
            required.append(issue)
        else:optional.append(item.reason+' '+issue.correction)
    return original.model_copy(update={'issues':required,'suggestions':(original.suggestions+optional)[:4]})


def _check_task(ledger,task_id,owner,parent,inputs,check,fingerprint,path):
    child=ledger.read(task_id)
    if (child.status!='completed' or child.task.parent_id!=parent or child.task.owner!=owner
        or child.task.inputs!=inputs or not child.observations or child.observations[-1].fingerprint!=fingerprint
        or ledger.failures(child,child.observations[-1])
        or not any(c.check==check and c.report==str(path.resolve()) for c in child.observations[-1].checks)):
        raise ValueError('Quality review lacks completed, current reviewer evidence')


def load_quality_review(ledger,state,review,suite,reference):
    digest=proposal_hash(suite);path=_path(ledger,state,digest)
    if reference.get('report')!=str(path.resolve()) or path.stat().st_size>100000:
        raise ValueError('Quality review report is outside its proposal binding')
    raw=path.read_bytes();fingerprint=hashlib.sha256(raw).hexdigest();packet=json.loads(raw)
    expected={'version':2,'job_id':ledger.job_id,'parent_task_id':state.task.id,'parent_revision':state.revision,
        'review_fingerprint':review['fingerprint'],'proposal_fingerprint':digest,'task_id':reference['task_id']}
    if any(packet.get(key)!=value for key,value in expected.items()) or reference.get('fingerprint')!=fingerprint:
        raise ValueError('Quality review belongs to another proposal/revision or its evidence changed')
    inputs={'parent_revision':state.revision,'review_fingerprint':review['fingerprint'],'proposal_fingerprint':digest}
    _check_task(ledger,packet['task_id'],'acceptance_reviewer',state.task.id,inputs,'scenario_review',fingerprint,path)
    original=AcceptanceCritique.model_validate(packet['original_decision']);_validate(original,suite)
    decision=AcceptanceCritique.model_validate(packet['decision']);_validate(decision,suite)
    if original.issues:
        scope=packet['scope_assessment']
        _check_task(ledger,scope['task_id'],'requirements_reviewer',packet['task_id'],inputs,'scope_assessment',fingerprint,path)
        if decision!=_scoped_decision(original,ScopeAssessment.model_validate(scope['decision']),review):
            raise ValueError('Effective quality findings differ from their scope assessment')
    elif decision!=original:raise ValueError('Quality decision differs from its original review')
    return decision


def review_suite(ledger,state,agents,review,suite,authorize):
    authorize();ledger.assert_active(state)
    if state.task.owner!='qa' or agents.model_name!=review['binding']['model']:
        raise ValueError('Scenario review requires the approved QA task/model')
    data=suite.model_dump();digest=proposal_hash(data);path=_path(ledger,state,digest)
    if path.exists():
        packet=json.loads(path.read_text(encoding='utf-8'))
        reference={'task_id':packet['task_id'],'report':str(path.resolve()),'fingerprint':hashlib.sha256(path.read_bytes()).hexdigest()}
        decision=load_quality_review(ledger,state,review,data,reference)
    else:
        child=ledger.reserve_action(ledger.start(ledger.create(Task(parent_id=state.task.id,owner='acceptance_reviewer',
            goal='Review whether proposed scenarios can distinguish requested behavior from plausible failures.',
            inputs={'parent_revision':state.revision,'review_fingerprint':review['fingerprint'],'proposal_fingerprint':digest},
            required_checks=['scenario_review']))),'acceptance_reviewer')
        inputs=review['binding']['inputs']
        context={'original_request':inputs['original_request'],
            'human_clarifications':inputs.get('human_clarifications',[]),
            'human_review_feedback':inputs.get('human_review_feedback',[]),
            'approved_criteria':review['draft']['acceptance_criteria'],
            'proposed_suite':data,'review_fingerprint':review['fingerprint'],'proposal_fingerprint':digest}
        if len(json.dumps(context,separators=(',',':')))>22000:
            ledger.pause(child,'Scenario review exceeds context budget',action_finished=True)
            raise ValueError('Scenario review exceeds context budget; split scope without dropping requirements')
        previous=getattr(agents,'invocation_context',{});activity=getattr(agents,'activity',None);scope_child=None;scope=None
        try:
            record_handoff(ledger.store,ledger.job_id,'acceptance_qa','acceptance_reviewer',
                'Review scenario effectiveness against requirements before freezing; no implementation supplied.',context,
                agents=agents,task_id=child.task.id,parent_task_id=state.task.id,task_state=child)
            agents.activity=lambda status,payload:ledger.store.event(ledger.job_id,status,payload,update_status=False)
            decision=AcceptanceCritique.model_validate(agents.generate(AcceptanceCritique,INSTRUCTION,context,coding=True))
            authorize();ledger.assert_active(state);_validate(decision,data)
            original=decision
            if original.issues:
                scope_child=ledger.reserve_action(ledger.start(ledger.create(Task(parent_id=child.task.id,owner='requirements_reviewer',
                    goal='Separate missing required test behavior from optional scope expansion.',inputs=child.task.inputs,
                    required_checks=['scope_assessment']))),'requirements_reviewer')
                scope_context={key:context[key] for key in ['original_request','human_clarifications','human_review_feedback','approved_criteria','review_fingerprint','proposal_fingerprint']}
                scope_context['proposed_blockers']=[issue.model_dump() for issue in original.issues]
                record_handoff(ledger.store,ledger.job_id,'acceptance_reviewer','requirements_reviewer',
                    'Ground proposed blockers in agreed requirements; optional coverage cannot expand app scope.',scope_context,
                    agents=agents,task_id=scope_child.task.id,parent_task_id=child.task.id,task_state=scope_child)
                assessment=ScopeAssessment.model_validate(agents.generate(ScopeAssessment,SCOPE_INSTRUCTION,scope_context,coding=True))
                authorize();ledger.assert_active(state);decision=_scoped_decision(original,assessment,review)
                scope={'task_id':scope_child.task.id,'decision':assessment.model_dump()}
            packet={'version':2,'job_id':ledger.job_id,'parent_task_id':state.task.id,'parent_revision':state.revision,
                'review_fingerprint':review['fingerprint'],'proposal_fingerprint':digest,'task_id':child.task.id,
                'original_decision':original.model_dump(),'decision':decision.model_dump(),'scope_assessment':scope,
                'scope':'Test-quality and requirements-scope model review only; no execution or app success.'}
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('x',encoding='utf-8',newline='\n') as output:output.write(json.dumps(packet,indent=2))
            fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
            if scope_child:
                ledger.observe(scope_child,Observation(revision=scope_child.revision,fingerprint=fingerprint,checks=[CheckEvidence(
                    check='scope_assessment',exit_code=0,fingerprint=fingerprint,report=str(path.resolve()),
                    summary='Scope judgment recorded; only requirement-grounded findings may block QA.')]))
            ledger.observe(child,Observation(revision=child.revision,fingerprint=fingerprint,checks=[CheckEvidence(
                check='scenario_review',exit_code=0,fingerprint=fingerprint,report=str(path.resolve()),
                summary='Review proposal validated; findings must be resolved before contract freezing.')]))
            reference={'task_id':child.task.id,'report':str(path.resolve()),'fingerprint':fingerprint}
        except Exception:
            if scope_child and ledger.read(scope_child.task.id).status=='running':
                ledger.pause(ledger.read(scope_child.task.id),'Requirements scope review needs inspection',action_finished=True)
            ledger.pause(ledger.read(child.task.id),'Scenario review needs inspection',action_finished=True)
            raise
        finally:agents.invocation_context=previous;agents.activity=activity
    if decision.issues:raise ValueError('Independent QA review requires revision: '+decision.model_dump_json())
    return reference
