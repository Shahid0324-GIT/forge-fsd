import hashlib
import json

import pytest

from forge.coordinator import TaskCoordinator
from forge.persistence import JobStore
from forge.senior_review import SeniorReviewer
from forge.tasks import CheckEvidence,Dependency,Observation,RecoveryPlan,Task,TaskLedger
from forge.provider_errors import ProviderResourceError


FP='a'*64


@pytest.fixture
def ledger(tmp_path):
    store=JobStore(tmp_path/'jobs.sqlite3')
    return TaskLedger(store,store.create({'description':'Build a small app'}))


def evidence(passed=True,fp=FP):
    return [CheckEvidence(check='functional',exit_code=0 if passed else 1,fingerprint=fp,
                          report='functional.json',summary='Actual check observation')]


def retry(_failed,_child):
    return RecoveryPlan(diagnosis='The current approach did not resolve the failure',
        strategy='Inspect the interface and use the actual check output to correct it',action='retry',owner='builder')


def create(ledger,limit=12):
    return ledger.create(Task(owner='builder',goal='Implement requested behavior',required_checks=['functional']),action_limit=limit)


def test_explicit_controller_blocker_pauses_without_review_or_fake_failure(ledger):
    from forge.tasks import TaskBlockedError
    task=create(ledger)
    def blocked(_):raise TaskBlockedError('Saved proposal repeats the same reviewed protocol conflict')
    result=TaskCoordinator(ledger,{'builder':blocked},
        lambda *_:pytest.fail('Known blockers must not spend another review call'),lambda:FP).run(task.task.id)
    assert result.status=='paused' and result.inflight_role is None
    assert result.actions_used==1 and not result.observations
    assert 'reviewed protocol conflict' in result.pause_reason
    assert result.pause_kind!='provider_resource'


def test_recovery_continues_beyond_old_two_attempt_cap_and_reviews_stalls(ledger):
    attempts=[];reviews=[]
    def worker(state):
        attempts.append(state)
        return evidence(passed=len(attempts)==5)
    def reviewer(failed,child):
        reviews.append((failed,child));return retry(failed,child)
    task=create(ledger)
    result=TaskCoordinator(ledger,{'builder':worker},reviewer,lambda:FP).run(task.task.id)
    assert result.status=='completed' and len(attempts)==5
    assert len(reviews)==3 and result.actions_used==8
    assert all(child.task.parent_id==task.task.id for _,child in reviews)
    assert all(child.task.owner=='senior_reviewer' for _,child in reviews)
    assert all(t.status=='completed' for t in ledger.list())
    assert ledger.store.read(ledger.job_id)['status']=='RECEIVED'


def test_reviewer_reassigns_design_problem_to_planner(ledger):
    seen=[]
    def builder(state):seen.append(state.task.owner);return evidence(False)
    def planner(state):
        seen.append(state.task.owner)
        assert state.recovery.strategy=='Reconcile the shared response contract'
        return evidence()
    def reviewer(failed,child):
        return RecoveryPlan(diagnosis='Builder cannot change an upstream interface',
            strategy='Reconcile the shared response contract',action='reassign',owner='planner')
    task=create(ledger)
    result=TaskCoordinator(ledger,{'builder':builder,'planner':planner},reviewer,lambda:FP).run(task.task.id)
    assert seen==['builder','builder','planner'] and result.status=='completed'


def test_owner_routing_hands_off_evidence_without_extra_model_review_or_budget(ledger):
    seen=[]
    def builder(state):seen.append(state.task.owner);return evidence(False)
    def backend(state):seen.append(state.task.owner);return evidence()
    task=create(ledger)
    result=TaskCoordinator(ledger,{'builder':builder,'backend':backend},retry,lambda:FP,
        owner_router=lambda state:'backend' if state.observations else None).run(task.task.id)
    assert seen==['builder','backend'] and result.status=='completed'
    assert result.actions_used==2 and result.action_limit==task.action_limit and result.revision==task.revision
    assert result.task.required_checks==task.task.required_checks and len(result.observations)==2
    assert any(event['status']=='TASK_REASSIGNED' for event in ledger.store.read(ledger.job_id)['events'])


def test_owner_routing_cannot_create_a_new_worker(ledger):
    calls=[];task=create(ledger)
    result=TaskCoordinator(ledger,{'builder':lambda _:calls.append(1)},retry,lambda:FP,
        owner_router=lambda _:'unregistered').run(task.task.id)
    assert result.status=='paused' and not calls and 'unavailable' in result.pause_reason


def test_source_change_during_owner_routing_discards_the_handoff(ledger):
    fp=[FP];calls=[];task=create(ledger)
    def route(_):fp[0]='b'*64;return 'backend'
    def builder(_):calls.append('builder');return evidence(fp=fp[0])
    result=TaskCoordinator(ledger,{'builder':builder,'backend':lambda _:calls.append('backend')},retry,lambda:fp[0],owner_router=route).run(task.task.id)
    assert result.status=='completed' and calls==['builder']


def test_owner_handoff_does_not_extend_an_exhausted_budget(ledger):
    task=create(ledger,limit=1);calls=[]
    def builder(_):calls.append('builder');return evidence(False)
    result=TaskCoordinator(ledger,{'builder':builder,'backend':lambda _:calls.append('backend')},retry,lambda:FP,
        owner_router=lambda state:'backend' if state.observations else None).run(task.task.id)
    assert result.status=='paused' and result.actions_used==1 and calls==['builder']


def test_provider_resource_failure_pauses_without_app_observation_or_repair_review(ledger):
    task=create(ledger);calls=[]
    def worker(_):calls.append(1);raise ProviderResourceError('Provider request exceeds token limit')
    result=TaskCoordinator(ledger,{'builder':worker},retry,lambda:FP).run(task.task.id)
    assert result.status=='paused' and result.inflight_role is None
    assert result.actions_used==1 and not result.observations and len(ledger.list())==1 and calls==[1]
    resumed=ledger.resume(result)
    result=TaskCoordinator(ledger,{'builder':lambda _:evidence()},retry,lambda:FP).run(resumed.task.id)
    assert result.status=='completed' and result.actions_used==2


def test_provider_limit_during_review_pauses_parent_and_review_child(ledger):
    task=create(ledger)
    def reviewer(*_):raise ProviderResourceError('Provider rate limit')
    result=TaskCoordinator(ledger,{'builder':lambda _:evidence(False)},reviewer,lambda:FP).run(task.task.id)
    assert result.status=='paused' and result.actions_used==3 and len(result.observations)==2
    child=next(state for state in ledger.list() if state.task.parent_id==task.task.id)
    assert child.status=='paused' and child.inflight_role is None and not child.observations


@pytest.mark.parametrize('error',['RuntimeError: Groq API returned HTTP 413','ValueError: Source response did not complete normally'])
def test_legacy_capacity_error_history_retries_worker_without_stale_senior_escalation(ledger,error):
    task=ledger.start(create(ledger))
    for _ in range(2):
        task=ledger.reserve_action(task,'builder')
        task=ledger.observe(task,Observation(revision=task.revision,fingerprint=FP,error=error))
    def reviewer(*_):raise AssertionError('A quota response is not an app diagnosis')
    result=TaskCoordinator(ledger,{'builder':lambda _:evidence()},reviewer,lambda:FP).run(task.task.id)
    assert result.status=='completed' and result.actions_used==3 and len(result.observations)==3


def test_exhaustion_pauses_and_explicit_resume_keeps_attempt_history(ledger):
    task=create(ledger,limit=3)
    engine=TaskCoordinator(ledger,{'builder':lambda _:evidence(False)},retry,lambda:FP)
    paused=engine.run(task.task.id)
    assert paused.status=='paused' and paused.actions_used==3 and paused.recovery
    assert len(paused.observations)==2
    resumed=ledger.resume(paused,additional_actions=1)
    complete=TaskCoordinator(ledger,{'builder':lambda _:evidence()},retry,lambda:FP).run(resumed.task.id)
    assert complete.status=='completed' and len(complete.observations)==3


def test_invalid_reviewer_output_retries_then_pauses_without_weakening_checks(ledger):
    def invalid(*_):return {'passed':True,'required_checks':[]}
    task=create(ledger,limit=5)
    result=TaskCoordinator(ledger,{'builder':lambda _:evidence(False)},invalid,lambda:FP).run(task.task.id)
    assert result.status=='paused' and result.actions_used==5
    assert result.task.required_checks==['functional'] and result.review_error
    assert len(ledger.list())==4  # parent plus three actual review tasks
    assert all(t.status=='paused' for t in ledger.list())


def test_interrupted_action_is_not_dispatched_again(ledger):
    task=ledger.reserve_action(ledger.start(create(ledger)),'builder');calls=[]
    result=TaskCoordinator(ledger,{'builder':lambda _:calls.append(1)},retry,lambda:FP).run(task.task.id)
    assert not calls and result.status=='paused' and result.inflight_role=='builder'


def test_changed_artifacts_require_fresh_checks_even_after_completion(ledger):
    fingerprint=[FP];calls=[]
    def worker(_):calls.append(1);return evidence(fp=fingerprint[0])
    task=create(ledger)
    engine=TaskCoordinator(ledger,{'builder':worker},retry,lambda:fingerprint[0])
    first=engine.run(task.task.id)
    fingerprint[0]='b'*64
    second=engine.run(task.task.id)
    assert second.status=='completed' and second.revision==first.revision+1 and len(calls)==2
    assert second.observations[-1].fingerprint==fingerprint[0]


def test_stale_worker_check_does_not_mark_task_complete(ledger):
    task=create(ledger,limit=2)
    result=TaskCoordinator(ledger,{'builder':lambda _:evidence(fp='b'*64)},retry,lambda:FP).run(task.task.id)
    assert result.status=='paused'
    assert all('Rejected worker evidence' in item.error for item in result.observations)


def test_reviewer_requests_concrete_input_without_erasing_failed_work(ledger):
    def missing(*_):return RecoveryPlan(diagnosis='Required service credentials are unavailable',
        strategy='Wait for the approved service configuration',action='request_input',owner='builder',
        question='Which supported deployment target should this app use?')
    task=ledger.create(Task(owner='builder',goal='Resolve the missing approved service configuration',
        required_checks=['functional'],allow_review_questions=True))
    result=TaskCoordinator(ledger,{'builder':lambda _:evidence(False)},missing,lambda:FP).run(task.task.id)
    assert result.status=='paused' and result.pause_reason.endswith('?')
    assert len(result.observations)==2


def test_senior_model_handoff_uses_real_child_identity_and_restores_context(ledger):
    task=ledger.start(create(ledger))
    task=ledger.observe(task,Observation(revision=1,fingerprint=FP,checks=evidence(False)))
    child=ledger.create(Task(parent_id=task.task.id,owner='senior_reviewer',goal='Diagnose this failure',required_checks=['proposal']))
    class Agent:
        invocation_context={'actor':'coordinator','task_id':task.task.id}
        activity=None
        def generate(self,schema,instruction,data,**_):
            assert data['original_goal']==task.task.goal
            assert data['recent_observations'][0]['checks'][0]['exit_code']==1
            assert data['current_evidence']['fingerprint']==FP
            assert data['current_evidence']['checks'][0]['summary']==task.observations[-1].checks[0].summary
            assert self.invocation_context['task_id']==child.task.id
            assert self.invocation_context['parent_task_id']==task.task.id
            return schema.model_validate(retry(None,None).model_dump())
    agent=Agent();previous=agent.invocation_context.copy()
    assert SeniorReviewer(agent,ledger,{'builder'})(task,child).action=='retry'
    assert agent.invocation_context==previous and agent.activity is None
    handoff=ledger.store.read(ledger.job_id)['events'][-1]['payload']
    assert handoff['task_id']==child.task.id and handoff['parent_task_id']==task.task.id


def test_review_report_fingerprint_matches_persisted_bytes(ledger):
    task=create(ledger,limit=3)
    TaskCoordinator(ledger,{'builder':lambda _:evidence(False)},retry,lambda:FP).run(task.task.id)
    child=next(t for t in ledger.list() if t.task.parent_id==task.task.id)
    check=child.observations[-1].checks[0]
    from pathlib import Path
    assert hashlib.sha256(Path(check.report).read_bytes()).hexdigest()==check.fingerprint
    assert json.loads(Path(check.report).read_text())['scope'].startswith('Recovery proposal validation only')


def test_senior_review_distinguishes_current_checks_from_latest_tool_error(ledger):
    task=ledger.start(create(ledger))
    old=CheckEvidence(check='functional',exit_code=1,fingerprint=FP,report='old.json',summary='Old missing import')
    task=ledger.observe(task,Observation(revision=1,fingerprint=FP,checks=[old]))
    current='b'*64
    new=CheckEvidence(check='functional',exit_code=1,fingerprint=current,report='current.json',summary='Current parse error')
    task=ledger.observe(task,Observation(revision=1,fingerprint=current,checks=[new]))
    task=ledger.observe(task,Observation(revision=1,fingerprint=current,error='Repair cycle rejected: earlier failed workspace'))
    child=ledger.create(Task(parent_id=task.task.id,owner='senior_reviewer',goal='Review current failure',required_checks=['proposal']))
    class Agent:
        def generate(self,schema,instruction,data,**_):
            assert data['current_evidence']['fingerprint']==current
            assert data['current_evidence']['checks'][0]['report']=='current.json'
            assert data['latest_tool_error'].startswith('Repair cycle rejected:')
            assert 'previous_strategy' not in data and 'history, not instructions' in instruction
            assert 'previous_unsuccessful_strategy' not in data
            assert all(o['fingerprint']==current for o in data['recent_observations'])
            return schema.model_validate(retry(None,None).model_dump())
    SeniorReviewer(Agent(),ledger,{'builder'})(task,child)


def test_restarted_pause_rechecks_changed_source_before_senior_handoff(ledger):
    task=create(ledger,limit=2)
    paused=TaskCoordinator(ledger,{'builder':lambda _:evidence(False)},retry,lambda:FP).run(task.task.id)
    reopened=TaskLedger(JobStore(ledger.store.path),ledger.job_id)
    resumed=reopened.resume(reopened.read(paused.task.id),additional_actions=2)
    calls=[];reviews=[];current='b'*64
    def worker(state):
        calls.append(state);return evidence(fp=current)
    result=TaskCoordinator(reopened,{'builder':worker},lambda *args:reviews.append(args),lambda:current).run(resumed.task.id)
    assert result.status=='completed' and len(calls)==1 and not reviews
    assert result.observations[-1].fingerprint==current
    assert result.observations[:2]==paused.observations


def test_source_changing_during_review_cannot_apply_old_reassignment(ledger):
    fingerprint=[FP];builders=[];planners=[]
    def worker(state):
        builders.append(state);return evidence(len(builders)>2,fp=fingerprint[0])
    def reviewer(*_):
        fingerprint[0]='b'*64
        return RecoveryPlan(diagnosis='Old interface failure',strategy='Change the old contract',action='reassign',owner='planner')
    def planner(state):planners.append(state);return evidence(fp=fingerprint[0])
    result=TaskCoordinator(ledger,{'builder':worker,'planner':planner},reviewer,lambda:fingerprint[0]).run(create(ledger).task.id)
    assert result.status=='completed' and len(builders)==3 and not planners
    assert result.recovery is None and result.task.owner=='builder'
    child=next(t for t in ledger.list() if t.task.owner=='senior_reviewer')
    assert child.status=='paused' and 'Artifacts changed during review' in child.observations[-1].checks[0].summary


def test_upstream_revision_during_worker_invalidates_result_after_reopen(ledger):
    upstream=ledger.start(create(ledger))
    upstream=ledger.observe(upstream,Observation(revision=1,fingerprint=FP,checks=evidence()))
    downstream=ledger.create(Task(owner='builder',goal='Implement the approved interface',required_checks=['functional'],
        dependencies=[Dependency(task_id=upstream.task.id,revision=upstream.revision)]))
    def worker(_):
        ledger.revise(upstream,upstream.task.model_copy(update={'inputs':{'interface':'new contract'}}))
        return evidence()
    result=TaskCoordinator(ledger,{'builder':worker},retry,lambda:FP).run(downstream.task.id)
    reopened=TaskLedger(JobStore(ledger.store.path),ledger.job_id)
    assert result.status=='needs_refresh' and not result.observations
    assert reopened.read(result.task.id)==result
    calls=[]
    TaskCoordinator(reopened,{'builder':lambda _:calls.append(1)},retry,lambda:FP).run(result.task.id)
    assert not calls
