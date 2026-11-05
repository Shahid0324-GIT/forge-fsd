"""Independent review of a proposed test suite, bound to that exact proposal."""
from forge.execution_models import execution_model
import hashlib
import json
from pathlib import Path
from typing import Annotated,Literal,Union

from pydantic import Field,create_model

from forge.handoffs import record_handoff
from forge.browser_capabilities import browser_capabilities
from forge.scenario_quality import exact_observation_conflicts,protocol_facts
from forge.tasks import CheckEvidence,Envelope,Observation,Task,TaskBlockedError,TaskConflict
from forge.provider_errors import ProviderResourceError


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
source or excuse missing requested functionality. coverage_limitations with
coverage=partial disclose checks the protocol cannot execute: do not require those
as browser assertions or treat the executable part as a complete criterion pass.
Return one finding per zero-based
issue index. classification=required_behavior needs an exact relevant requirement
quote from the provided requirements/criteria/feedback. classification=optional_coverage
means the finding exceeds the agreed scope and cannot block QA. For optional findings explain that they exceed
the agreed scope. Never claim execution, app correctness or human approval.'''
SCOPE_INSTRUCTION+=''' Use reviewed_scenarios and scenario_protocol_facts to check what
the proposed tests already do. A demand for a different tool is optional when the
trusted protocol already performs the requested behavior. In particular visit is
Playwright page.goto document navigation, never client-router navigation; repeated
same-path visits already implement a full reload. Do not demand an unsupported
reload verb or a server restart for a browser-reload requirement.'''


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
An uncovered entry with coverage=partial explicitly limits that criterion's scenario
claim to checked_behavior. Assess the effectiveness of that executable part, not the
disclosed unverified remainder. Do not demand removing useful assertions or promote
partial coverage to complete coverage. Missing supported behavior still blocks review.
Use verification_capabilities.assertion_semantics: assert_text compares the target's
ENTIRE visible innerText exactly after whitespace normalization, never a substring.
For a named region containing headings and several rows, a single-row expected value
does not match that region. Check exact_observation_conflicts: different exact values
for the same target with no intervening action require an explicitly requested
asynchronous transition; otherwise block the inconsistent proposal. Do not ask the
builder to change correct app behavior to satisfy incompatible assertions. Request
one full-region expectation or appropriate smaller semantic targets instead.
Return assessed_criteria containing exactly the covered indices. Return issues with
existing criterion/scenario references and concrete corrections; issues=[] only when
you find no material gaps against the actual agreed scope. Do not rewrite tests or claim execution,
application correctness or human approval. This review is advisory model judgment,
not a semantic proof. Return concise findings, not private reasoning.'''
INSTRUCTION+=''' Treat navigation_semantics and scenario_protocol_facts as authoritative
facts about the trusted runner. visit always uses page.goto for full document
navigation; a repeated same-path visit resets JavaScript state while preserving
the browser context. It is not SPA routing and needs no additional reload action.
Assess exactly the supplied covered_criteria, including nonconsecutive indices.'''


def critique_schema(suite):
    """Bind review bookkeeping and issue references to this actual proposed suite."""
    covered=sorted({index for case in suite['scenarios'] for index in case['criteria']})
    variants=[create_model('ScenarioIssue'+str(number),__base__=TestIssue,
        criterion=(Literal[tuple(case['criteria'])],...),scenario=(Literal[case['id']],...))
        for number,case in enumerate(suite['scenarios'])]
    issue=variants[0] if len(variants)==1 else Annotated[Union[tuple(variants)],Field(discriminator='scenario')] if variants else TestIssue
    return create_model('AcceptanceCritique',__base__=AcceptanceCritique,
        assessed_criteria=(tuple[tuple(Literal[index] for index in covered)],...),
        issues=(list[issue],Field(max_length=8 if variants else 0)))


def proposal_hash(suite):
    return hashlib.sha256(json.dumps(suite,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _validate(decision,suite):
    cases={case['id']:set(case['criteria']) for case in suite['scenarios']}
    covered={index for indices in cases.values() for index in indices}
    if set(decision.assessed_criteria)!=covered or len(set(decision.assessed_criteria))!=len(decision.assessed_criteria):
        raise ValueError('Quality review must assess every covered criterion exactly once')
    if any(issue.scenario not in cases or issue.criterion not in cases[issue.scenario] for issue in decision.issues):
        raise ValueError('Quality findings must reference a scenario covering that criterion')


def _review_decision(agents,schema,instruction,context,validate,authorize):
    """Reviewer protocol defects belong to the reviewer, not the QA author."""
    request=dict(context)
    for attempt in range(2):
        authorize();decision=None
        try:
            decision=agents.generate(schema,instruction,request,coding=True)
            validate(decision)
            return schema.model_validate(decision.model_dump(mode='json'))
        except (TaskConflict,TaskBlockedError):raise
        except ValueError as exc:
            if attempt:
                raise TaskBlockedError('Independent reviewer returned an invalid decision after one correction; '
                    'the test proposal has not been rejected. Inspect reviewer evidence. '+str(exc)) from exc
            request={**context,'previous_decision':decision.model_dump() if decision is not None else None,
                'review_validation_error':str(exc),
                'correction_instruction':'Correct your own review decision against the original proposed suite and requirements. '
                    'Assess every covered criterion exactly once and use only existing criterion/scenario references. '
                    'Do not rewrite the test proposal or invent a test defect to excuse an invalid review.'}


def _protocol_hash():
    return hashlib.sha256(b''.join(Path(__file__).with_name(name).read_bytes() for name in
        ['acceptance_review.py','browser_capabilities.py','scenario_quality.py'])+
        browser_capabilities()['protocol_sha256'].encode()).hexdigest()


def _path(ledger,state,digest,version=3):
    prefix='quality-v2' if version==2 else 'quality-v3-'+_protocol_hash()
    return ledger.store.path.parent/'acceptance-plans'/ledger.job_id/f'{prefix}-{state.task.id}-r{state.revision}-{digest}.json'


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
    digest=proposal_hash(suite)
    paths={str(_path(ledger,state,digest,v).resolve()):v for v in (2,3)}
    if reference.get('report') not in paths:
        raise ValueError('Quality review report is outside its proposal binding')
    path=Path(reference['report']);version=paths[str(path)]
    if path.stat().st_size>100000:raise ValueError('Quality review exceeds its artifact budget')
    raw=path.read_bytes();fingerprint=hashlib.sha256(raw).hexdigest();packet=json.loads(raw)
    expected={'version':version,'job_id':ledger.job_id,'parent_task_id':state.task.id,'parent_revision':state.revision,
        'review_fingerprint':review['fingerprint'],'proposal_fingerprint':digest,'task_id':reference['task_id']}
    if any(packet.get(key)!=value for key,value in expected.items()) or reference.get('fingerprint')!=fingerprint:
        raise ValueError('Quality review belongs to another proposal/revision or its evidence changed')
    if version==3 and packet.get('review_protocol_sha256')!=_protocol_hash():
        raise ValueError('Quality review belongs to another verification protocol')
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
    if state.task.owner!='qa' or agents.model_name!=execution_model(ledger.job_id,ledger.store,review):
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
            'verification_capabilities':browser_capabilities(),
            'covered_criteria':sorted({index for case in data['scenarios'] for index in case['criteria']}),
            'scenario_protocol_facts':protocol_facts(data),
            'exact_observation_conflicts':exact_observation_conflicts(data),
            'proposed_suite':data,'review_fingerprint':review['fingerprint'],'proposal_fingerprint':digest}
        if len(json.dumps(context,separators=(',',':')))>22000:
            ledger.pause(child,'Scenario review exceeds context budget',action_finished=True)
            raise ProviderResourceError('Scenario review exceeds context budget; split scope without dropping requirements')
        previous=getattr(agents,'invocation_context',{});activity=getattr(agents,'activity',None);scope_child=None;scope=None
        try:
            record_handoff(ledger.store,ledger.job_id,'acceptance_qa','acceptance_reviewer',
                'Review scenario effectiveness against requirements before freezing; no implementation supplied.',context,
                agents=agents,task_id=child.task.id,parent_task_id=state.task.id,task_state=child)
            agents.activity=lambda status,payload:ledger.store.event(ledger.job_id,status,payload,update_status=False)
            def current_review():
                authorize();ledger.assert_active(state);ledger.assert_active(child)
            decision=_review_decision(agents,critique_schema(data),INSTRUCTION,context,
                lambda value:_validate(value,data),current_review)
            authorize();ledger.assert_active(state);_validate(decision,data)
            original=decision
            if original.issues:
                scope_child=ledger.reserve_action(ledger.start(ledger.create(Task(parent_id=child.task.id,owner='requirements_reviewer',
                    goal='Separate missing required test behavior from optional scope expansion.',inputs=child.task.inputs,
                    required_checks=['scope_assessment']))),'requirements_reviewer')
                scope_context={key:context[key] for key in ['original_request','human_clarifications','human_review_feedback','approved_criteria','review_fingerprint','proposal_fingerprint']}
                scope_context['proposed_blockers']=[issue.model_dump() for issue in original.issues]
                scope_context['coverage_limitations']=data['uncovered']
                scope_context['verification_capabilities']=context['verification_capabilities']
                mentioned={issue.scenario for issue in original.issues}
                scope_context['reviewed_scenarios']=[case for case in data['scenarios'] if case['id'] in mentioned]
                scope_context['scenario_protocol_facts']={key:value for key,value in context['scenario_protocol_facts'].items() if key in mentioned}
                record_handoff(ledger.store,ledger.job_id,'acceptance_reviewer','requirements_reviewer',
                    'Ground proposed blockers in agreed requirements; optional coverage cannot expand app scope.',scope_context,
                    agents=agents,task_id=scope_child.task.id,parent_task_id=child.task.id,task_state=scope_child)
                def current_scope():
                    current_review();ledger.assert_active(scope_child)
                assessment=_review_decision(agents,ScopeAssessment,SCOPE_INSTRUCTION,scope_context,
                    lambda value:_scoped_decision(original,value,review),current_scope)
                authorize();ledger.assert_active(state);decision=_scoped_decision(original,assessment,review)
                scope={'task_id':scope_child.task.id,'decision':assessment.model_dump()}
            packet={'version':3,'review_protocol_sha256':_protocol_hash(),'job_id':ledger.job_id,'parent_task_id':state.task.id,'parent_revision':state.revision,
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
