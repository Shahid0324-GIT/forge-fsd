from types import SimpleNamespace

import pytest

from forge.handoffs import record_handoff
from forge.hybrid import HybridRouter,LOCAL,CLOUD
from forge.models import HYBRID_MODEL
from forge.persistence import JobStore
from forge.provider_errors import ProviderResourceError
from forge.tasks import Task,TaskLedger,Observation,TaskConflict


@pytest.fixture
def setup(tmp_path):
    store=JobStore(tmp_path/'jobs.sqlite3');job=store.create({'model':HYBRID_MODEL});ledger=TaskLedger(store,job)
    state=ledger.reserve_action(ledger.start(ledger.create(Task(owner='builder',goal='Implement a small page',required_checks=['build']))),'builder')
    calls=[]
    class Client:
        def __init__(self,model):self.model_name=model
        def generate(self,*args,**kwargs):
            calls.append(self.model_name);self.last_call_identity={'call_id':'call-'+self.model_name,'model':self.model_name};return self.model_name
        def generate_source(self,*args,**kwargs):return self.generate()
    facade=SimpleNamespace(model_name=HYBRID_MODEL,trace_directory=tmp_path/'calls')
    router=HybridRouter(Client)
    def handoff(current=state,role='builder'):
        record_handoff(store,job,'coordinator',role,'Work on current evidence',{},agents=facade,task_id=current.task.id,parent_task_id=current.task.parent_id,task_state=current)
    handoff()
    return store,ledger,state,facade,router,calls,handoff


def test_routine_work_starts_local_and_records_actual_model(setup):
    store,ledger,state,facade,router,calls,_=setup
    assert router.invoke(facade,'generate_source','instruction',{})==LOCAL
    event=store.read(ledger.job_id)['events'][-1]
    assert event['status']=='MODEL_ROUTED' and event['payload']['model']==LOCAL
    assert event['payload']['revision']==state.revision and facade.last_call_identity['model']==LOCAL


@pytest.mark.parametrize('role',['planner','senior_reviewer','acceptance_reviewer','requirements_reviewer','coverage_reviewer'])
def test_planning_and_quality_roles_use_explicit_cloud_policy(setup,role):
    _,_,state,facade,router,calls,handoff=setup;handoff(state,role)
    assert router.invoke(facade,'generate',object,'instruction',{})==CLOUD and calls==[CLOUD]


def test_invalid_local_output_escalates_only_after_observation_and_stays_across_restart(setup):
    store,ledger,state,facade,router,calls,handoff=setup
    assert router.invoke(facade,'generate_source','instruction',{})==LOCAL
    state=ledger.observe(state,Observation(revision=state.revision,fingerprint='a'*64,error='ValueError: Invalid SourceText output: bad response'))
    state=ledger.reserve_action(state,'builder');handoff(state)
    assert router.invoke(facade,'generate_source','instruction',{})==CLOUD
    restarted=HybridRouter(router.factory)
    assert restarted.invoke(facade,'generate_source','instruction',{})==CLOUD
    assert calls==[LOCAL,CLOUD,CLOUD]


def test_new_task_revision_does_not_inherit_an_old_escalation(setup):
    _,ledger,state,facade,router,calls,handoff=setup;handoff(state,'senior_reviewer')
    assert router.invoke(facade,'generate_source','instruction',{})==CLOUD
    state=ledger.revise(state,state.task);state=ledger.reserve_action(ledger.start(state),'builder');handoff(state)
    assert router.invoke(facade,'generate_source','instruction',{})==LOCAL


def test_stale_task_handoff_cannot_invoke_either_provider(setup):
    _,ledger,state,facade,router,calls,_=setup
    ledger.revise(state,state.task)
    with pytest.raises(TaskConflict):router.invoke(facade,'generate_source','instruction',{})
    assert calls==[]


def test_same_revision_new_dispatch_requires_a_fresh_handoff_version(setup):
    _,ledger,state,facade,router,calls,_=setup
    state=ledger.observe(state,Observation(revision=state.revision,fingerprint='a'*64,error='Failed tool'))
    ledger.reserve_action(state,'builder')
    with pytest.raises(TaskConflict):router.invoke(facade,'generate_source','instruction',{})
    assert calls==[]


def test_pinned_single_model_job_cannot_be_silently_routed(setup):
    store,ledger,state,facade,router,calls,_=setup
    store.event(ledger.job_id,'MODEL_SELECTED',{'model':LOCAL},update_status=False)
    with pytest.raises(ValueError,match='not selected'):router.invoke(facade,'generate_source','instruction',{})
    assert calls==[]


def test_cloud_resource_pause_never_downgrades_or_replays_a_call(setup):
    _,_,state,facade,router,calls,handoff=setup;handoff(state,'senior_reviewer')
    class Limited:
        def generate_source(self,*_):calls.append(CLOUD);raise ProviderResourceError('Quota pause')
    router.factory=lambda _:Limited()
    with pytest.raises(ProviderResourceError):router.invoke(facade,'generate_source','instruction',{})
    assert calls==[CLOUD]


def test_qa_child_uses_current_parent_stall_evidence(setup):
    _,ledger,state,facade,router,calls,handoff=setup
    for _ in range(2):
        state=ledger.observe(state,Observation(revision=state.revision,fingerprint='a'*64,error='Tool correction failed'))
        state=ledger.reserve_action(state,'builder')
    child=ledger.reserve_action(ledger.start(ledger.create(Task(parent_id=state.task.id,owner='qa',goal='Diagnose failure',
        inputs={'input_revision':state.revision},required_checks=['diagnosis']))),'qa')
    handoff(child,'qa')
    assert router.invoke(facade,'generate',object,'instruction',{})==CLOUD
    ledger.revise(state,state.task)
    with pytest.raises(TaskConflict):router.invoke(facade,'generate',object,'instruction',{})


def test_real_agent_facade_routes_both_output_transports_from_saved_handoff(setup):
    from forge.agents import OllamaAgents
    store,ledger,state,_,router,calls,_=setup
    agent=OllamaAgents(HYBRID_MODEL);agent._hybrid=router
    record_handoff(store,ledger.job_id,'coordinator','builder','Current source task',{},
        agents=agent,task_id=state.task.id,task_state=state)
    assert agent.generate_source('source instruction',{})==LOCAL
    record_handoff(store,ledger.job_id,'coordinator','planner','Current planning task',{},
        agents=agent,task_id=state.task.id,task_state=state)
    assert agent.generate(object,'plan instruction',{})==CLOUD
    assert calls==[LOCAL,CLOUD] and agent.last_call_identity['model']==CLOUD


def test_handoff_rejects_the_snapshot_that_precedes_a_new_dispatch(setup):
    store,ledger,state,facade,_,calls,_=setup
    updated=ledger.observe(state,Observation(revision=state.revision,fingerprint='a'*64,error='Tool failed'))
    ledger.reserve_action(updated,'builder')
    with pytest.raises(TaskConflict):
        record_handoff(store,ledger.job_id,'coordinator','builder','Expired inputs',{},
            agents=facade,task_id=state.task.id,task_state=state)
    assert calls==[]


def test_provider_initialization_failure_cannot_reuse_a_previous_call_identity(setup):
    _,_,state,facade,router,_,handoff=setup
    router.invoke(facade,'generate_source','instruction',{})
    assert facade.last_call_identity
    handoff(state,'planner')
    def unavailable(_):raise ValueError('Provider configuration unavailable')
    router.factory=unavailable
    with pytest.raises(ValueError,match='configuration'):router.invoke(facade,'generate',object,'instruction',{})
    assert facade.last_call_identity=={}
