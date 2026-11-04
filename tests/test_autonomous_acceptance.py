import json

import pytest

from forge.autonomous_acceptance import AcceptanceSuite,acceptance_worker,load_acceptance,suite_path,validate_coverage
from forge.persistence import JobStore
from forge.tasks import Observation,Task,TaskLedger


def proposal():
    return {'scenarios':[{'id':'counter_actions','criteria':[1,2],'steps':[
        {'action':'visit','path':'/'},
        {'action':'assert_visible','target':{'by':'text','value':'Count: 0'}},
        {'action':'click','target':{'by':'role','value':'button','name':'Increment'}},
        {'action':'assert_visible','target':{'by':'text','value':'Count: 1'}}]}],
        'uncovered':[{'criterion':3,'reason':'Database restart is not supported by the browser protocol.'}]}


@pytest.fixture
def context(tmp_path):
    store=JobStore(tmp_path/'artifacts/jobs.sqlite3');job=store.create();ledger=TaskLedger(store,job)
    review={'fingerprint':'a'*64,'binding':{'inputs':{'original_request':'A counter with persistence after restart',
        'human_clarifications':['Increment adds one'],'human_review_feedback':['Keep the current count visible']},'model':'fake'},
        'draft':{'design':'Independent app design','acceptance_criteria':['Starts at zero','Increment adds one','Survives database restart']}}
    state=ledger.reserve_action(ledger.start(ledger.create(Task(owner='qa',goal='Define independent checks',
        inputs={'review_fingerprint':review['fingerprint']},required_checks=['acceptance_contract']))),'qa')
    class Agent:
        model_name='fake'
        activity=None
        invocation_context={'actor':'coordinator'}
        def generate(self,schema,instruction,data,**_):
            self.data=data
            return schema.model_validate(proposal())
    return ledger,state,review,Agent()


def test_independent_qa_keeps_requirements_and_previous_assertions_without_repeating_build_assignments(context):
    import hashlib
    from forge.autonomous_acceptance import proposal_context
    ledger,state,review,_=context
    review['draft'].update(files=[{'path':'app/page.tsx','owner':'frontend','purpose':'UI assignment '*400}],
        test_strategy='Earlier implementation proposal '*100,
        assumptions=['Single user'],database='none')
    original=json.loads(json.dumps(review['draft']))
    directory=suite_path(ledger,state).parent;directory.mkdir(parents=True,exist_ok=True)
    previous=proposal();(directory/f'proposal-{state.task.id}-r{state.revision}-a1.json').write_text(json.dumps(previous),encoding='utf-8')
    data=proposal_context(ledger,state,review)
    assert data['approved_design']['acceptance_criteria']==original['acceptance_criteria']
    assert data['approved_design']['design']==original['design'] and data['approved_design']['assumptions']==original['assumptions']
    assert data['previous_proposal']==previous
    assert data['original_request']==review['binding']['inputs']['original_request']
    assert data['human_clarifications']==review['binding']['inputs']['human_clarifications']
    assert review['draft']==original
    for key in ['files','test_strategy']:
        assert key not in data['approved_design']
        assert data['approved_design_omitted'][key]==hashlib.sha256(json.dumps(original[key],sort_keys=True).encode()).hexdigest()
    assert len(json.dumps(data))<len(json.dumps(original))


def freeze(context):
    ledger,state,review,agent=context
    checks=acceptance_worker(ledger,state,agent,review,lambda:None)
    state=ledger.observe(state,Observation(revision=state.revision,fingerprint=checks[0].fingerprint,checks=checks))
    return state,load_acceptance(ledger,state,review)


def test_contract_is_requirements_derived_frozen_and_outside_source_workspace(context):
    ledger,_,review,agent=context;previous=agent.invocation_context.copy()
    state,contract=freeze(context)
    assert agent.data['original_request']==review['binding']['inputs']['original_request']
    assert agent.data['human_review_feedback']==['Keep the current count visible']
    assert not {'source','current_source','repair_focus'} & agent.data.keys()
    assert contract['suite']['uncovered'][0]['criterion']==3
    assert suite_path(ledger,state).is_relative_to(ledger.store.path.parent/'acceptance-plans')
    assert agent.invocation_context==previous and agent.activity is None


def test_duplicate_dispatch_cannot_replace_a_frozen_contract(context):
    ledger,state,review,agent=context
    acceptance_worker(ledger,state,agent,review,lambda:None)
    original=suite_path(ledger,state).read_bytes()
    with pytest.raises(FileExistsError):acceptance_worker(ledger,state,agent,review,lambda:None)
    assert suite_path(ledger,state).read_bytes()==original


def test_retry_receives_the_rejected_proposal_and_exact_conflicting_criterion(context):
    ledger,state,review,agent=context
    normal_generate=agent.generate
    def conflicting(schema,instruction,data,**kwargs):
        data=proposal();data['uncovered']=[{'criterion':2,'reason':'Mistaken duplicate claim'}]
        return schema.model_validate(data)
    agent.generate=conflicting
    with pytest.raises(ValueError,match=r'\[2\]') as failed:acceptance_worker(ledger,state,agent,review,lambda:None)
    assert not suite_path(ledger,state).exists()
    from forge.autonomous_acceptance import suite_fingerprint
    state=ledger.observe(state,Observation(revision=state.revision,fingerprint=suite_fingerprint(ledger,state),error=str(failed.value)))
    state=ledger.reserve_action(state,'qa');agent.generate=normal_generate
    checks=acceptance_worker(ledger,state,agent,review,lambda:None)
    assert agent.data['previous_proposal']['uncovered'][0]['criterion']==2
    assert '[2]' in agent.data['protocol_errors'][0]
    assert len(list(suite_path(ledger,state).parent.glob('proposal-*.json')))==2
    assert checks[0].exit_code==0


@pytest.mark.parametrize('change',['bytes','review','unfinished','revision'])
def test_stale_changed_or_unfinished_contract_cannot_supply_acceptance_evidence(context,change):
    ledger,_,review,_=context;state,contract=freeze(context)
    if change=='bytes':suite_path(ledger,state).write_text(json.dumps({'suite':proposal()}),encoding='utf-8')
    if change=='review':review['fingerprint']='b'*64
    if change=='unfinished':state=state.model_copy(update={'status':'running'})
    if change=='revision':ledger.revise(state,state.task)
    with pytest.raises(ValueError):load_acceptance(ledger,state,review)


def test_revoked_authorization_after_model_response_prevents_freezing(context):
    ledger,state,review,agent=context;calls=[]
    def authorize():
        calls.append(True)
        if len(calls)>1:raise ValueError('Approval revoked')
    with pytest.raises(ValueError,match='Approval revoked'):acceptance_worker(ledger,state,agent,review,authorize)
    assert not suite_path(ledger,state).exists()


def test_interaction_without_observed_result_is_saved_for_revision_not_frozen(context):
    ledger,state,review,agent=context
    def weak(schema,*_,**kwargs):
        data=proposal();data['scenarios'][0]['steps'].pop()
        return schema.model_validate(data)
    agent.generate=weak
    with pytest.raises(ValueError,match='unobserved_interaction'):
        acceptance_worker(ledger,state,agent,review,lambda:None)
    assert not suite_path(ledger,state).exists()
    assert len(list(suite_path(ledger,state).parent.glob('proposal-*.json')))==1


def test_legacy_contract_is_readable_without_claiming_new_quality_validation(context):
    import hashlib
    ledger,state,review,agent=context
    checks=acceptance_worker(ledger,state,agent,review,lambda:None)
    path=suite_path(ledger,state);packet=json.loads(path.read_text());packet.pop('scenario_quality_version')
    packet['suite']['scenarios'][0]['steps'].pop()  # Older protocol permitted baseline-only tests.
    path.write_text(json.dumps(packet),encoding='utf-8');digest=hashlib.sha256(path.read_bytes()).hexdigest()
    state=ledger.observe(state,Observation(revision=state.revision,fingerprint=digest,
        checks=[checks[0].model_copy(update={'fingerprint':digest})]))
    assert 'scenario_quality_version' not in load_acceptance(ledger,state,review)


@pytest.mark.parametrize('change',[
    lambda d:d['scenarios'][0]['steps'][0].update(path='//external.example/'),
    lambda d:d['scenarios'][0]['steps'][0].update(path='http://127.0.0.1:8787/'),
    lambda d:d['scenarios'][0]['steps'][0].update(path='/\\external'),
    lambda d:d['scenarios'][0].update(steps=[{'action':'visit','path':'/'},{'action':'click','target':{'by':'text','value':'Click'}}]),
    lambda d:d['scenarios'][0].update(criteria=[0,2]),
    lambda d:d.update(uncovered=[]),
    lambda d:d['uncovered'][0].update(criterion=1),
    lambda d:d['scenarios'].append(d['scenarios'][0]),
    lambda d:d['scenarios'][0]['steps'].append({'action':'evaluate','code':'fetch("http://control-plane")'}),
    lambda d:d['scenarios'][0]['steps'][1].update(target={'by':'role','value':'text'}),
    lambda d:d['scenarios'][0]['steps'][1].update(action='assert_text',target={'by':'role','value':'textbox'},value='0'),
    lambda d:d['scenarios'][0]['steps'][1].update(action='assert_value',target={'by':'role','value':'heading'},value='0'),
])
def test_test_protocol_rejects_external_navigation_code_empty_assertions_and_incomplete_coverage(change):
    data=proposal();change(data)
    with pytest.raises(ValueError):validate_coverage(AcceptanceSuite.model_validate(data),3)


def test_partial_contract_preserves_executable_assertions_and_unverified_remainder(context):
    ledger,state,review,agent=context
    review['draft']['acceptance_criteria'][1]='Increment adds one and announces the result to screen readers'
    data=proposal();data['uncovered'].append({'criterion':2,'coverage':'partial',
        'checked_behavior':'Increment changes the visible count from zero to one',
        'reason':'Screen-reader announcements cannot be exercised by this browser protocol'})
    agent.generate=lambda schema,*args,**kwargs:schema.model_validate(data)
    _,contract=freeze(context)
    assert contract['suite']['scenarios']==AcceptanceSuite.model_validate(data).model_dump()['scenarios']
    assert contract['suite']['uncovered']==data['uncovered']
    assert contract['suite']['uncovered'][1]['coverage']=='partial'


@pytest.mark.parametrize('change',[
    lambda d:d['uncovered'][-1].update(checked_behavior=''),
    lambda d:d['uncovered'][-1].update(criterion=3),
    lambda d:d['uncovered'][-1].update(coverage='complete'),
])
def test_partial_coverage_needs_explicit_behavior_and_real_scenario(change):
    data=proposal();data['uncovered']=[{'criterion':3,'reason':'Restart unavailable'},
        {'criterion':2,'coverage':'partial','checked_behavior':'Visible increment',
         'reason':'Screen reader execution unavailable'}]
    change(data)
    with pytest.raises(ValueError):validate_coverage(AcceptanceSuite.model_validate(data),3)


def test_identical_rejected_proposal_after_senior_review_stops_paid_retry_cycle(context):
    from forge.tasks import RecoveryPlan,TaskBlockedError
    from forge.autonomous_acceptance import suite_fingerprint
    ledger,state,review,agent=context
    with pytest.raises(ValueError,match='Needs stronger assertions'):
        acceptance_worker(ledger,state,agent,review,lambda:None,
            review_quality=lambda suite:(_ for _ in ()).throw(ValueError('Needs stronger assertions')))
    state=ledger.observe(state,Observation(revision=state.revision,fingerprint=suite_fingerprint(ledger,state),
        error='Needs stronger assertions'))
    state=ledger.recover(state,RecoveryPlan(diagnosis='Unchanged QA proposal',strategy='Change the assertions',
        action='retry',owner='qa'),{'qa'})
    state=ledger.reserve_action(state,'qa')
    with pytest.raises(TaskBlockedError,match='identical rejected proposal after senior review'):
        acceptance_worker(ledger,state,agent,review,lambda:None,
            review_quality=lambda suite:pytest.fail('No repeated reviewer dispatch'))
    assert len(list(suite_path(ledger,state).parent.glob('proposal-*.json')))==2
    assert not suite_path(ledger,state).exists()


def test_revised_qa_excludes_old_errors_and_trace_fallback(context):
    from forge.autonomous_acceptance import proposal_context
    ledger,state,review,_=context
    trace=ledger.store.path.parent/'old-call.json'
    def record(revision):
        trace.write_text(json.dumps({'job_id':ledger.job_id,'task_revision':revision,
            'output':json.dumps(proposal()),'output_truncated':False}),encoding='utf-8')
        ledger.store.event(ledger.job_id,'AGENT_CALL_COMPLETED',{'schema':'AcceptanceSuite',
            'task_id':state.task.id,'task_revision':revision,'report':str(trace.resolve())},update_status=False)
    record(state.revision)
    state=ledger.observe(state,Observation(revision=state.revision,fingerprint='a'*64,error='Old contract feedback'))
    state=ledger.revise(state,state.task)
    data=proposal_context(ledger,state,review)
    assert data['previous_proposal'] is None and data['protocol_errors']==[]
    record(state.revision)
    assert proposal_context(ledger,state,review)['previous_proposal']==AcceptanceSuite.model_validate(proposal()).model_dump()


def test_task_handoff_binds_non_hybrid_invocations_to_current_revision(context):
    from forge.handoffs import record_handoff
    ledger,state,_,agent=context
    packet=record_handoff(ledger.store,ledger.job_id,'coordinator','qa','Current QA inputs',{},
        agents=agent,task_id=state.task.id,task_state=state)
    assert packet['task_revision']==agent.invocation_context['task_revision']==state.revision
    record_handoff(ledger.store,ledger.job_id,'qa','helper','Unversioned helper',{},agents=agent)
    assert 'task_revision' not in agent.invocation_context and 'task_version' not in agent.invocation_context


def test_real_completion_event_can_recover_current_revision_proposal(context):
    from types import SimpleNamespace
    from forge.agents import OllamaAgents
    from forge.handoffs import record_handoff
    from forge.autonomous_acceptance import proposal_context
    from test_agents import FakeModel
    ledger,state,review,_=context
    expected=AcceptanceSuite.model_validate(proposal())
    agent=OllamaAgents.__new__(OllamaAgents);agent.model_name='fake'
    agent.model=FakeModel({'raw':SimpleNamespace(content=expected.model_dump_json(),
        response_metadata={'done_reason':'stop'}),'parsed':expected,'parsing_error':None})
    agent.trace_directory=ledger.store.path.parent/'model-calls';agent.activity=lambda status,data:ledger.store.event(
        ledger.job_id,status,data,update_status=False)
    record_handoff(ledger.store,ledger.job_id,'coordinator','qa','Current inputs',{},
        agents=agent,task_id=state.task.id,task_state=state)
    agent.generate(AcceptanceSuite,'Return a contract',{})
    event=ledger.store.read(ledger.job_id)['events'][-1]
    assert event['status']=='AGENT_CALL_COMPLETED'
    assert event['payload']['task_revision']==state.revision
    assert event['payload']['task_version']==state.version
    assert proposal_context(ledger,state,review)['previous_proposal']==expected.model_dump()
