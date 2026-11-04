"""Small event-backed task ledger. Task completion is not application readiness."""
import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel,ConfigDict,Field,JsonValue,model_validator

from forge.persistence import now


class Envelope(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)


class Dependency(Envelope):
    task_id: str
    revision: int = Field(ge=1)


class Task(Envelope):
    id: str = Field(default_factory=lambda:uuid4().hex)
    parent_id: str | None = None
    owner: str = Field(min_length=1,max_length=80)
    goal: str = Field(min_length=1,max_length=4000)
    inputs: dict[str,JsonValue] = Field(default_factory=dict)
    dependencies: list[Dependency] = Field(default_factory=list,max_length=20)
    required_checks: list[str] = Field(min_length=1,max_length=30)
    allow_review_questions: bool = False

    @model_validator(mode='after')
    def unique_references(self):
        ids=[d.task_id for d in self.dependencies]
        if len(ids)!=len(set(ids)) or self.id in ids:raise ValueError('Task dependencies must be unique and cannot reference itself')
        if len(self.required_checks)!=len(set(self.required_checks)) or any(not c.strip() for c in self.required_checks):
            raise ValueError('Required checks must have unique, nonempty names')
        return self


class CheckEvidence(Envelope):
    check: str = Field(min_length=1,max_length=160)
    exit_code: int
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    report: str = Field(min_length=1,max_length=2000)
    summary: str = Field(default='',max_length=2000)


class Observation(Envelope):
    revision: int = Field(ge=1)
    fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    checks: list[CheckEvidence] = Field(default_factory=list,max_length=50)
    error: str = Field(default='',max_length=4000)

    @model_validator(mode='after')
    def coherent_evidence(self):
        if len({c.check for c in self.checks})!=len(self.checks):raise ValueError('Check evidence names must be unique')
        if any(c.fingerprint!=self.fingerprint for c in self.checks):raise ValueError('Checks do not belong to the observed artifact fingerprint')
        return self


class RecoveryPlan(Envelope):
    diagnosis: str = Field(min_length=1,max_length=2000)
    strategy: str = Field(min_length=1,max_length=3000)
    action: Literal['retry','reassign','request_input']
    owner: str = Field(min_length=1,max_length=80)
    question: str = Field(default='',max_length=1000,description='Empty for retry/reassign. A concrete blocking question only for request_input.')

    @model_validator(mode='after')
    def actionable_question(self):
        if self.action=='request_input' and not self.question.strip():raise ValueError('Input requests need a concrete question')
        if self.action!='request_input' and self.question:raise ValueError('Questions require request_input; retry/reassign must not ask unnecessary user questions')
        return self


class TaskState(Envelope):
    task: Task
    version: int = 1
    revision: int = 1
    status: Literal['queued','running','needs_refresh','paused','completed','cancelled'] = 'queued'
    actions_used: int = 0
    inflight_role: str | None = None
    action_limit: int = Field(default=12,ge=1)
    observations: list[Observation] = Field(default_factory=list)
    no_progress: int = 0
    reviewed_observations: int = -1
    recovery: RecoveryPlan | None = None
    review_error: str = ''
    pause_reason: str = ''
    pause_kind: Literal['','provider_resource'] = ''


class TaskConflict(ValueError):
    pass


class TaskLedger:
    def __init__(self,store,job_id):self.store=store;self.job_id=job_id

    def _states(self,db):
        if not db.execute('SELECT 1 FROM jobs WHERE id=? AND deleted_at IS NULL',(self.job_id,)).fetchone():raise KeyError(self.job_id)
        rows=db.execute("SELECT payload FROM events WHERE job_id=? AND status LIKE 'TASK_%' ORDER BY sequence",(self.job_id,)).fetchall()
        states={}
        for row in rows:
            payload=json.loads(row[0])
            if 'task_state' in payload:
                state=TaskState.model_validate(payload['task_state']);states[state.task.id]=state
        return states

    def read(self,task_id):
        with self.store.connect() as db:return self._states(db)[task_id]

    def list(self):
        with self.store.connect() as db:return list(self._states(db).values())

    def assert_active(self,state,db=None):
        current=self._states(db)[state.task.id] if db is not None else self.read(state.task.id)
        if (current.version!=state.version or current.revision!=state.revision
            or current.status!='running' or current.task.owner!=state.task.owner):
            raise TaskConflict('Tool request belongs to a stale or inactive task')
        return current

    def _save(self,db,state,event,summary):
        db.execute('INSERT INTO events(job_id,timestamp,status,payload) VALUES (?,?,?,?)',
            (self.job_id,now(),event,json.dumps({'task_id':state.task.id,'parent_task_id':state.task.parent_id,
                'owner':state.task.owner,'revision':state.revision,'summary':summary,'task_state':state.model_dump()})))

    @staticmethod
    def _dependencies(task,states,ready=False):
        for dependency in task.dependencies:
            if dependency.task_id not in states:raise ValueError('Dependency is outside this job')
            upstream=states[dependency.task_id]
            if ready and (upstream.revision!=dependency.revision or upstream.status!='completed'):
                raise TaskConflict('Dependencies are unfinished or their revisions changed; refresh the task inputs')
        def visit(task_id,stack):
            if task_id in stack:raise ValueError('Task dependency cycle')
            current=task if task_id==task.id else states[task_id].task
            for d in current.dependencies:visit(d.task_id,stack | {task_id})
        visit(task.id,set())

    def create(self,task,*,action_limit=12):
        task=Task.model_validate(task)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');states=self._states(db)
            if task.id in states:raise TaskConflict('Task already exists')
            if task.parent_id and task.parent_id not in states:raise ValueError('Parent task is outside this job')
            self._dependencies(task,states)
            state=TaskState(task=task,action_limit=action_limit)
            self._save(db,state,'TASK_CREATED','Task created with explicit ownership and input revision.')
        return state

    def update(self,task_id,version,event,summary,mutate):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');states=self._states(db);state=states[task_id]
            if state.version!=version:raise TaskConflict('Task changed while work was in flight')
            mutate(state,states)
            state.version+=1
            state=TaskState.model_validate(state.model_dump())
            self._save(db,state,event,summary)
        return state

    def start(self,state):
        def mutate(current,states):
            if current.status!='queued':raise TaskConflict('Only queued tasks can start')
            self._dependencies(current.task,states,ready=True);current.status='running'
        return self.update(state.task.id,state.version,'TASK_STARTED','Task dispatched to its owner.',mutate)

    def reserve_action(self,state,role):
        def mutate(current,_):
            if current.status!='running':raise TaskConflict('Task is not running')
            if current.inflight_role is not None:raise TaskConflict('Previous dispatch needs reconciliation')
            if current.actions_used>=current.action_limit:raise TaskConflict('Action budget exhausted; pause and resume with an explicit extension')
            current.actions_used+=1
            current.inflight_role=role
        return self.update(state.task.id,state.version,'TASK_ACTION_STARTED',f'Dispatching {role}; resource usage is saved before invocation.',mutate)

    @staticmethod
    def failures(state,observation):
        checks={c.check:c for c in observation.checks}
        missing={name for name in state.task.required_checks if name not in checks or checks[name].exit_code!=0}
        if observation.error:missing.add('execution_error')
        return missing

    def observe(self,state,observation):
        observation=Observation.model_validate(observation)
        def mutate(current,_):
            if current.status!='running' or observation.revision!=current.revision:raise TaskConflict('Observation belongs to an inactive or stale task revision')
            previous=next((o for o in reversed(current.observations) if o.revision==current.revision),None)
            failures=self.failures(current,observation)
            improved=previous is not None and failures < self.failures(current,previous)
            current.no_progress=0 if improved else current.no_progress+1
            current.observations.append(observation)
            current.inflight_role=None
            if not failures:current.status='completed';current.pause_reason=''
        return self.update(state.task.id,state.version,'TASK_OBSERVED','Recorded controller-observed evidence; model claims do not complete a task.',mutate)

    def recover(self,state,plan,roles):
        plan=RecoveryPlan.model_validate(plan)
        def mutate(current,_):
            if current.status!='running':raise TaskConflict('Task is not running')
            if plan.owner not in roles:raise ValueError('Reviewer selected an unavailable role')
            if plan.action=='request_input' and not current.task.allow_review_questions:
                raise ValueError('This technical task does not delegate user-question authority to the reviewer')
            if plan.action=='retry' and plan.owner!=current.task.owner:raise ValueError('Changing ownership requires a reassign action')
            current.recovery=plan;current.reviewed_observations=len(current.observations)
            current.review_error=''
            current.inflight_role=None
            if plan.action=='reassign':current.task.owner=plan.owner
            if plan.action=='request_input':current.status='paused';current.pause_reason=plan.question
        return self.update(state.task.id,state.version,'TASK_RECOVERY_PLANNED','Senior review supplied a recovery strategy, not a passing result.',mutate)

    def review_failed(self,state,error):
        def mutate(current,_):
            if current.status!='running':raise TaskConflict('Task is not running')
            current.inflight_role=None;current.review_error=error[:4000]
        return self.update(state.task.id,state.version,'TASK_REVIEW_FAILED',error[:4000],mutate)

    def reassign(self,state,owner,roles,reason):
        """Route known evidence to an existing worker; grant no new file ownership."""
        def mutate(current,_):
            if current.status!='running' or current.inflight_role is not None:
                raise TaskConflict('Only idle running tasks can be reassigned')
            if owner not in roles:raise ValueError('Handoff selected an unavailable worker')
            current.task.owner=owner;current.recovery=None;current.review_error=''
            current.reviewed_observations=0;current.no_progress=0
        return self.update(state.task.id,state.version,'TASK_REASSIGNED',reason,mutate)

    def pause(self,state,reason,*,action_finished=False,kind=''):
        if kind not in {'','provider_resource'}:raise ValueError('Unknown pause kind')
        def mutate(current,_):
            if current.status not in {'queued','running','paused'}:raise TaskConflict('Task cannot pause in its current state')
            current.status='paused';current.pause_reason=reason;current.pause_kind=kind
            if action_finished:current.inflight_role=None
        return self.update(state.task.id,state.version,'TASK_PAUSED',reason,mutate)

    def resume(self,state,*,additional_actions=0,reconciled=False):
        if additional_actions<0:raise ValueError('Cannot reduce the action budget on resume')
        def mutate(current,_):
            if current.status!='paused':raise TaskConflict('Only paused tasks can resume')
            if current.inflight_role is not None and not reconciled:raise TaskConflict('Inspect interrupted action outcomes before resuming')
            current.inflight_role=None
            current.action_limit+=additional_actions;current.status='queued';current.pause_reason='';current.pause_kind=''
        return self.update(state.task.id,state.version,'TASK_RESUMED','Resumed saved work without discarding attempts or review.',mutate)

    def revise(self,state,task):
        task=Task.model_validate(task)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');states=self._states(db);current=states[state.task.id]
            if current.version!=state.version:raise TaskConflict('Task changed while work was in flight')
            if task.id!=current.task.id or task.parent_id!=current.task.parent_id:raise ValueError('Task identity and parent cannot be rewritten')
            self._dependencies(task,states)
            current.task=task;current.revision+=1;current.version+=1;current.status='queued'
            current.inflight_role=None
            current.no_progress=0;current.recovery=None;current.review_error='';current.pause_reason='';current.pause_kind=''
            self._save(db,current,'TASK_REVISED','Inputs revised; previous evidence does not complete this revision.')
            changed={current.task.id}
            pending=True
            while pending:
                pending=False
                for descendant in states.values():
                    if descendant.task.id not in changed and any(d.task_id in changed for d in descendant.task.dependencies):
                        descendant.revision+=1;descendant.version+=1;descendant.status='needs_refresh'
                        descendant.no_progress=0;descendant.recovery=None;descendant.review_error='';descendant.pause_reason='Upstream inputs changed; refresh the task and dependency revisions.'
                        descendant.inflight_role=None
                        self._save(db,descendant,'TASK_INVALIDATED',descendant.pause_reason)
                        changed.add(descendant.task.id);pending=True
        return current
