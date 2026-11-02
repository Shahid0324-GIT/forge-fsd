import pytest
from pydantic import ValidationError

from forge.persistence import JobStore
from forge.tasks import CheckEvidence,Dependency,Observation,RecoveryPlan,Task,TaskConflict,TaskLedger


FP='a'*64


@pytest.fixture
def ledger(tmp_path):
    store=JobStore(tmp_path/'jobs.sqlite3')
    return TaskLedger(store,store.create({'description':'Build a small app'}))


def task(**extra):
    return Task(owner='builder',goal='Implement the requested behavior',required_checks=['build','functional'],**extra)


def observation(state,failed=(),*,fingerprint=FP):
    return Observation(revision=state.revision,fingerprint=fingerprint,checks=[
        CheckEvidence(check=name,exit_code=int(name in failed),fingerprint=fingerprint,report='evidence/'+name+'.json')
        for name in state.task.required_checks])


def complete(ledger,state):
    running=ledger.start(state)
    return ledger.observe(running,observation(running))


def test_tasks_survive_restart_without_changing_application_readiness(ledger):
    state=complete(ledger,ledger.create(task()))
    reopened=TaskLedger(JobStore(ledger.store.path),ledger.job_id)
    assert reopened.read(state.task.id)==state
    assert state.status=='completed'
    assert reopened.store.read(ledger.job_id)['status']=='RECEIVED'


def test_stale_inflight_result_cannot_complete_revised_task(ledger):
    running=ledger.start(ledger.create(task()))
    revised=ledger.revise(running,running.task.model_copy(update={'inputs':{'contract':'new design'}}))
    with pytest.raises(TaskConflict,match='in flight'):ledger.observe(running,observation(running))
    restarted=ledger.start(revised)
    with pytest.raises(TaskConflict,match='stale task revision'):ledger.observe(restarted,observation(running))
    assert ledger.read(running.task.id).status=='running'


def test_partial_or_stale_evidence_cannot_complete_task(ledger):
    running=ledger.start(ledger.create(task()))
    partial=Observation(revision=1,fingerprint=FP,checks=[CheckEvidence(check='build',exit_code=0,fingerprint=FP,report='build.json')])
    assert ledger.observe(running,partial).status=='running'
    with pytest.raises(ValidationError,match='fingerprint'):
        Observation(revision=1,fingerprint=FP,checks=[CheckEvidence(check='functional',exit_code=0,fingerprint='b'*64,report='old.json')])


def test_dependency_revision_change_invalidates_all_consumers(ledger):
    parent=complete(ledger,ledger.create(task()))
    child=complete(ledger,ledger.create(task(parent_id=parent.task.id,dependencies=[Dependency(task_id=parent.task.id,revision=1)])))
    grandchild=complete(ledger,ledger.create(task(parent_id=child.task.id,dependencies=[Dependency(task_id=child.task.id,revision=1)])))
    revised=ledger.revise(parent,parent.task.model_copy(update={'inputs':{'type':'agent-owned new contract'}}))
    assert revised.status=='queued' and revised.revision==2
    assert ledger.read(child.task.id).status=='needs_refresh'
    assert ledger.read(grandchild.task.id).status=='needs_refresh'
    assert len(ledger.read(child.task.id).observations)==1
    with pytest.raises(TaskConflict):ledger.start(ledger.read(child.task.id))
    refreshed=ledger.revise(ledger.read(child.task.id),child.task.model_copy(update={
        'dependencies':[Dependency(task_id=parent.task.id,revision=2)],'inputs':{'type':'new contract'}}))
    with pytest.raises(TaskConflict,match='unfinished'):ledger.start(refreshed)
    complete(ledger,revised)
    assert ledger.start(refreshed).status=='running'


def test_revision_cannot_introduce_dependency_cycles(ledger):
    parent=ledger.create(task())
    child=ledger.create(task(dependencies=[Dependency(task_id=parent.task.id,revision=1)]))
    with pytest.raises(ValueError,match='cycle'):
        ledger.revise(parent,parent.task.model_copy(update={'dependencies':[Dependency(task_id=child.task.id,revision=1)]}))
    assert ledger.read(parent.task.id)==parent


def test_foreign_dependencies_and_deleted_jobs_are_rejected(ledger):
    with pytest.raises(ValueError,match='outside this job'):
        ledger.create(task(dependencies=[Dependency(task_id='other-job-task',revision=1)]))
    state=ledger.create(task());ledger.store.trash(ledger.job_id,'RECEIVED')
    with pytest.raises(KeyError):ledger.start(state)


def test_source_changes_alone_are_not_counted_as_progress(ledger):
    state=ledger.start(ledger.create(task()))
    state=ledger.observe(state,observation(state,failed=['functional']))
    state=ledger.observe(state,observation(state,failed=['functional'],fingerprint='b'*64))
    assert state.no_progress==2 and state.status=='running'
    state=ledger.observe(state,observation(state))
    assert state.no_progress==0 and state.status=='completed'


def test_budget_pause_is_resumable_and_preserves_history(ledger):
    state=ledger.start(ledger.create(task(),action_limit=1))
    state=ledger.reserve_action(state,'builder')
    state=ledger.observe(state,observation(state,failed=['functional']))
    with pytest.raises(TaskConflict,match='budget exhausted'):ledger.reserve_action(state,'builder')
    paused=ledger.pause(state,'Action budget reached')
    resumed=ledger.start(ledger.resume(paused,additional_actions=2))
    assert resumed.observations==state.observations and resumed.actions_used==1
    assert ledger.reserve_action(resumed,'senior_reviewer').actions_used==2


def test_interrupted_dispatch_is_not_silently_replayed(ledger):
    running=ledger.start(ledger.create(task()))
    dispatched=ledger.reserve_action(running,'builder')
    reopened=TaskLedger(JobStore(ledger.store.path),ledger.job_id)
    assert reopened.read(running.task.id).inflight_role=='builder'
    paused=reopened.pause(dispatched,'Interrupted action needs inspection')
    with pytest.raises(TaskConflict,match='Inspect interrupted'):reopened.resume(paused)
    assert reopened.resume(paused,reconciled=True).inflight_role is None


def test_review_can_reassign_but_cannot_claim_success_or_remove_checks(ledger):
    state=ledger.start(ledger.create(task()))
    plan=RecoveryPlan(diagnosis='The shared interface is inconsistent',strategy='Reconcile it before implementation',action='reassign',owner='planner')
    state=ledger.recover(state,plan,{'builder','planner'})
    assert state.task.owner=='planner' and state.status=='running'
    assert state.task.required_checks==['build','functional']
    with pytest.raises(ValidationError):RecoveryPlan.model_validate({**plan.model_dump(),'passed':True})
    with pytest.raises(ValueError,match='unavailable role'):
        ledger.recover(state,plan.model_copy(update={'owner':'unrestricted_shell'}),{'builder','planner'})
