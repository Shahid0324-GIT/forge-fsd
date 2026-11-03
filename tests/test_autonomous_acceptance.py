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
])
def test_test_protocol_rejects_external_navigation_code_empty_assertions_and_incomplete_coverage(change):
    data=proposal();change(data)
    with pytest.raises(ValueError):validate_coverage(AcceptanceSuite.model_validate(data),3)
