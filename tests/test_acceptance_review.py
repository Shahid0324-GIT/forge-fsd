from pathlib import Path

import pytest

from forge.acceptance_review import review_suite,load_quality_review
from forge.autonomous_acceptance import AcceptanceSuite,acceptance_worker,load_acceptance
from forge.tasks import Observation
from test_autonomous_acceptance import context,proposal


class Reviewer:
    model_name='fake'
    invocation_context={'actor':'coordinator'}
    activity=None
    def __init__(self,issues=None,required=True):self.issues=issues or [];self.calls=[];self.required=required
    def generate(self,schema,instruction,data,**_):
        self.calls.append(data)
        if schema.__name__=='ScopeAssessment':
            return schema.model_validate({'findings':[{'issue':index,'classification':'required_behavior' if self.required else 'optional_coverage',
                'requirement_quote':data['approved_criteria'][issue['criterion']-1] if self.required else '',
                'reason':'Required by the agreed behavior' if self.required else 'Additional optional coverage'}
                for index,issue in enumerate(data['proposed_blockers'])]})
        return schema.model_validate({'assessed_criteria':[1,2],'issues':self.issues})


def test_review_is_bound_to_proposal_and_has_no_generated_source(context):
    ledger,state,review,_=context;agent=Reviewer();original=agent.invocation_context.copy()
    suite=AcceptanceSuite.model_validate(proposal())
    reference=review_suite(ledger,state,agent,review,suite,lambda:None)
    assert load_quality_review(ledger,state,review,suite.model_dump(),reference).issues==[]
    assert not {'source','current_source','repair_focus'} & agent.calls[0].keys()
    assert agent.calls[0]['original_request']==review['binding']['inputs']['original_request']
    from forge.browser_capabilities import browser_capabilities
    assert agent.calls[0]['verification_capabilities']==browser_capabilities()
    assert agent.calls[0]['covered_criteria']==[1,2]
    assert 'scenario_protocol_facts' in agent.calls[0]
    assert agent.invocation_context==original and agent.activity is None
    assert review_suite(ledger,state,agent,review,suite,lambda:None)==reference and len(agent.calls)==1


def test_findings_block_freezing_and_repeated_proposal_reuses_exact_review(context):
    ledger,state,review,qa=context
    agent=Reviewer([{'criterion':2,'scenario':'counter_actions','reason':'Only one input is exercised',
        'correction':'Exercise another action and assert its result'}])
    for _ in range(2):
        with pytest.raises(ValueError,match='Independent QA review requires revision'):
            review_suite(ledger,state,agent,review,AcceptanceSuite.model_validate(proposal()),lambda:None)
    assert len(agent.calls)==2  # Critique plus one scope assessment, both cached.
    from forge.autonomous_acceptance import suite_path
    with pytest.raises(ValueError,match='Independent QA review requires revision'):
        acceptance_worker(ledger,state,qa,review,lambda:None,review_quality=lambda suite:review_suite(ledger,state,agent,review,suite,lambda:None))
    assert not suite_path(ledger,state).exists()


@pytest.mark.parametrize('change',['proposal','revision','bytes','review','child'])
def test_expired_or_tampered_review_cannot_authorize_contract(context,change):
    ledger,state,review,_=context;agent=Reviewer();suite=AcceptanceSuite.model_validate(proposal())
    reference=review_suite(ledger,state,agent,review,suite,lambda:None)
    if change=='proposal':suite.scenarios[0].steps[-1].target.value='Count: 99'
    if change=='revision':state=state.model_copy(update={'revision':state.revision+1})
    if change=='bytes':Path(reference['report']).write_text('{}')
    if change=='review':review['fingerprint']='b'*64
    if change=='child':
        child=ledger.read(reference['task_id']);ledger.revise(child,child.task)
    with pytest.raises((ValueError,OSError,KeyError)):
        load_quality_review(ledger,state,review,suite.model_dump(),reference)


def test_quality_evidence_is_required_again_when_loading_frozen_contract(context):
    ledger,state,review,qa=context;reviewer=Reviewer()
    checks=acceptance_worker(ledger,state,qa,review,lambda:None,
        review_quality=lambda suite:review_suite(ledger,state,reviewer,review,suite,lambda:None))
    state=ledger.observe(state,Observation(revision=state.revision,fingerprint=checks[0].fingerprint,checks=checks))
    contract=load_acceptance(ledger,state,review)
    Path(contract['quality_review']['report']).write_text('{}')
    with pytest.raises(ValueError):load_acceptance(ledger,state,review)


def test_changed_authorization_during_review_cannot_supply_evidence(context):
    ledger,state,review,_=context;calls=[]
    def authorize():
        calls.append(1)
        if len(calls)>1:raise ValueError('Approval changed')
    with pytest.raises(ValueError,match='Approval changed'):
        review_suite(ledger,state,Reviewer(),review,AcceptanceSuite.model_validate(proposal()),authorize)
    child=next(task for task in ledger.list() if task.task.owner=='acceptance_reviewer')
    assert child.status=='paused' and not child.observations


@pytest.mark.parametrize('decision',[
    {'assessed_criteria':[1],'issues':[]},
    {'assessed_criteria':[1,1,2],'issues':[]},
    {'assessed_criteria':[1,2],'issues':[{'criterion':2,'scenario':'invented','reason':'A finding','correction':'A correction'}]},
])
def test_review_must_assess_real_coverage_and_reference_existing_scenarios(context,decision):
    ledger,state,review,_=context
    class Invalid(Reviewer):
        def generate(self,schema,*_,**kwargs):return schema.model_validate(decision)
    with pytest.raises(ValueError):review_suite(ledger,state,Invalid(),review,AcceptanceSuite.model_validate(proposal()),lambda:None)


def test_reviewer_repairs_its_own_invalid_decision_without_rewriting_qa_suite(context):
    ledger,state,review,_=context
    class Correcting(Reviewer):
        def generate(self,schema,instruction,data,**kwargs):
            from forge.acceptance_review import AcceptanceCritique
            self.calls.append(data)
            return AcceptanceCritique.model_validate({'assessed_criteria':[1] if len(self.calls)==1 else [1,2],'issues':[]})
    agent=Correcting();suite=AcceptanceSuite.model_validate(proposal());original=suite.model_dump()
    reference=review_suite(ledger,state,agent,review,suite,lambda:None)
    assert len(agent.calls)==2
    assert agent.calls[1]['previous_decision']['assessed_criteria']==[1]
    assert 'every covered criterion' in agent.calls[1]['review_validation_error']
    assert agent.calls[1]['proposed_suite']==original==suite.model_dump()
    assert not load_quality_review(ledger,state,review,original,reference).issues


def test_repeated_invalid_review_pauses_qa_instead_of_generating_new_tests(context):
    from forge.tasks import TaskBlockedError
    ledger,state,review,qa=context
    class Invalid(Reviewer):
        def generate(self,schema,instruction,data,**kwargs):
            self.calls.append(data)
            return schema.model_validate({'assessed_criteria':[],'issues':[]})
    agent=Invalid()
    with pytest.raises(TaskBlockedError,match='test proposal has not been rejected'):
        acceptance_worker(ledger,state,qa,review,lambda:None,
            review_quality=lambda suite:review_suite(ledger,state,agent,review,suite,lambda:None))
    assert len(agent.calls)==2
    assert qa.data['previous_proposal'] is None
    assert all(task.status=='paused' for task in ledger.list() if task.task.owner=='acceptance_reviewer')


def test_review_pause_resumes_the_same_test_proposal_without_another_author_call(context):
    from forge.tasks import TaskBlockedError
    ledger,state,review,qa=context;calls=[];generate=qa.generate
    def author(*args,**kwargs):calls.append(1);return generate(*args,**kwargs)
    qa.generate=author
    with pytest.raises(TaskBlockedError):
        acceptance_worker(ledger,state,qa,review,lambda:None,
            review_quality=lambda _:(_ for _ in ()).throw(TaskBlockedError('Reviewer decision needs inspection')))
    state=ledger.pause(state,'Reviewer decision needs inspection',action_finished=True)
    state=ledger.reserve_action(ledger.start(ledger.resume(state)),'qa')
    reviewer=Reviewer()
    checks=acceptance_worker(ledger,state,qa,review,lambda:None,
        review_quality=lambda suite:review_suite(ledger,state,reviewer,review,suite,lambda:None))
    assert len(calls)==1 and checks[0].exit_code==0


def test_optional_coverage_suggestions_do_not_block_required_scope(context):
    ledger,state,review,_=context
    class Suggesting(Reviewer):
        def generate(self,schema,*_,**kwargs):return schema.model_validate({'assessed_criteria':[1,2],
            'issues':[],'suggestions':['Consider additional optional input cases in a later milestone.']})
    suite=AcceptanceSuite.model_validate(proposal())
    reference=review_suite(ledger,state,Suggesting(),review,suite,lambda:None)
    assert load_quality_review(ledger,state,review,suite.model_dump(),reference).suggestions


def test_changed_review_protocol_cannot_reuse_old_approval(context,monkeypatch):
    import forge.acceptance_review as module
    ledger,state,review,_=context;agent=Reviewer();suite=AcceptanceSuite.model_validate(proposal())
    reference=review_suite(ledger,state,agent,review,suite,lambda:None)
    monkeypatch.setattr(module,'_protocol_hash',lambda:'e'*64)
    with pytest.raises(ValueError,match='binding'):
        load_quality_review(ledger,state,review,suite.model_dump(),reference)
    fresh=review_suite(ledger,state,agent,review,suite,lambda:None)
    assert fresh['report']!=reference['report'] and len(agent.calls)==2


def test_scope_review_demotes_unrequested_blocker_and_preserves_its_evidence(context):
    ledger,state,review,_=context
    agent=Reviewer([{'criterion':2,'scenario':'counter_actions','reason':'Missing an unrequested feature',
        'correction':'Consider extra optional input handling'}],required=False)
    suite=AcceptanceSuite.model_validate(proposal());reference=review_suite(ledger,state,agent,review,suite,lambda:None)
    decision=load_quality_review(ledger,state,review,suite.model_dump(),reference)
    assert not decision.issues and decision.suggestions
    assert 'proposed_suite' not in agent.calls[1] and 'source' not in agent.calls[1]
    assert agent.calls[1]['reviewed_scenarios']==suite.model_dump()['scenarios']
    assert 'counter_actions' in agent.calls[1]['scenario_protocol_facts']
    import json
    packet=json.loads(Path(reference['report']).read_text())
    assert packet['original_decision']['issues'] and packet['scope_assessment']['decision']['findings'][0]['classification']=='optional_coverage'
    scope=ledger.read(packet['scope_assessment']['task_id']);ledger.revise(scope,scope.task)
    with pytest.raises(ValueError):load_quality_review(ledger,state,review,suite.model_dump(),reference)


@pytest.mark.parametrize('findings',[
    [{'issue':0,'classification':'required_behavior','requirement_quote':'An invented requirement','reason':'A blocker'}],
    [{'issue':0,'classification':'optional_coverage','reason':'Optional'},
     {'issue':0,'classification':'optional_coverage','reason':'Duplicate'}],
])
def test_scope_findings_need_real_quotes_and_exact_issue_references(context,findings):
    ledger,state,review,_=context
    class InvalidScope(Reviewer):
        def generate(self,schema,instruction,data,**kwargs):
            if schema.__name__=='ScopeAssessment':return schema.model_validate({'findings':findings})
            return super().generate(schema,instruction,data,**kwargs)
    agent=InvalidScope([{'criterion':2,'scenario':'counter_actions','reason':'A proposed issue','correction':'A correction'}])
    with pytest.raises(ValueError):review_suite(ledger,state,agent,review,AcceptanceSuite.model_validate(proposal()),lambda:None)
    assert all(task.status=='paused' for task in ledger.list() if task.task.owner in {'acceptance_reviewer','requirements_reviewer'})


def test_critique_wire_schema_binds_nonconsecutive_coverage_and_each_issue_scenario():
    from forge.acceptance_review import critique_schema
    data={'scenarios':[{'id':'edit','criteria':[1,3]},{'id':'reload','criteria':[7]}]}
    schema=critique_schema(data)
    assert list(schema.model_validate({'assessed_criteria':[1,3,7],'issues':[]}).assessed_criteria)==[1,3,7]
    for values in ([1,3],[1,3,6],[1,3,3]):
        with pytest.raises(ValueError):schema.model_validate({'assessed_criteria':values,'issues':[]})
    with pytest.raises(ValueError):schema.model_validate({'assessed_criteria':[1,3,7],
        'issues':[{'scenario':'edit','criterion':7,'reason':'A finding','correction':'A correction'}]})


def test_quality_review_expires_when_actual_runner_identity_changes(context,monkeypatch):
    import forge.acceptance_review as module
    from forge.browser_capabilities import browser_capabilities
    ledger,state,review,_=context;agent=Reviewer();suite=AcceptanceSuite.model_validate(proposal())
    reference=review_suite(ledger,state,agent,review,suite,lambda:None)
    changed=browser_capabilities();changed['protocol_sha256']='e'*64
    monkeypatch.setattr(module,'browser_capabilities',lambda:changed)
    with pytest.raises(ValueError,match='binding'):load_quality_review(ledger,state,review,suite.model_dump(),reference)
