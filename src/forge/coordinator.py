"""A bounded LangGraph task loop with evidence-driven senior-review escalation.

Workers execute through controller-owned adapters and return actual tool evidence,
not model-authored pass/fail claims. This module does not publish or deploy apps.
"""
import hashlib
import json
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END,START,StateGraph
from langsmith import tracing_context

from forge.tasks import CheckEvidence,Observation,RecoveryPlan,Task,TaskConflict


class LoopState(TypedDict,total=False):
    task_id: str
    next: str


class TaskCoordinator:
    def __init__(self,ledger,workers,reviewer,fingerprint,*,review_after=2):
        if review_after<1:raise ValueError('Review threshold must be positive')
        if not workers or 'senior_reviewer' in workers:raise ValueError('Register workers separately from the escalation reviewer')
        self.ledger=ledger;self.workers=dict(workers);self.reviewer=reviewer
        self.fingerprint=fingerprint;self.review_after=review_after
        graph=StateGraph(LoopState)
        graph.add_node('route',self._route);graph.add_node('worker',self._work)
        graph.add_node('senior_reviewer',self._review)
        graph.add_edge(START,'route')
        graph.add_conditional_edges('route',lambda state:state['next'],{'worker':'worker','review':'senior_reviewer','done':END})
        graph.add_edge('worker','route');graph.add_edge('senior_reviewer','route')
        self.graph=graph.compile()

    def run(self,task_id):
        current=self.ledger.read(task_id)
        # A lost process may have dispatched a side effect. Do not replay it blindly.
        if current.status=='running' and current.inflight_role is not None:
            return self.ledger.pause(current,'Interrupted dispatch requires artifact/tool outcome reconciliation before resume.')
        remaining=max(0,current.action_limit-current.actions_used)
        try:
            with tracing_context(enabled=False):
                self.graph.invoke({'task_id':task_id},{'recursion_limit':2*remaining+10})
        except TaskConflict:
            # An input revision/cancellation won the race; stale work is not accepted.
            return self.ledger.read(task_id)
        return self.ledger.read(task_id)

    def _route(self,state):
        current=self.ledger.read(state['task_id'])
        if current.status=='completed':
            try:unchanged=current.observations[-1].fingerprint==self.fingerprint()
            except Exception as exc:
                # Invalidate completion before recording an unavailable workspace.
                current=self.ledger.revise(current,current.task)
                self.ledger.pause(current,'Cannot inspect current artifacts: '+str(exc)[:1000])
                return {'next':'done'}
            if unchanged:return {'next':'done'}
            current=self.ledger.revise(current,current.task)
        if current.status not in {'queued','running'}:return {'next':'done'}
        if current.task.owner not in self.workers:
            self.ledger.pause(current,'Task owner has no registered worker: '+current.task.owner)
            return {'next':'done'}
        if current.status=='queued':
            try:current=self.ledger.start(current)
            except TaskConflict as exc:
                self.ledger.pause(current,str(exc));return {'next':'done'}
        if current.actions_used>=current.action_limit:
            self.ledger.pause(current,'Action budget reached. Work, evidence and recovery strategy are saved; resume with an explicit budget extension.')
            return {'next':'done'}
        stalled=(current.no_progress>=self.review_after or bool(current.review_error))
        reviewed=current.reviewed_observations==len(current.observations)
        return {'next':'review' if stalled and not reviewed else 'worker'}

    def _work(self,state):
        current=self.ledger.read(state['task_id'])
        dispatched=self.ledger.reserve_action(current,current.task.owner)
        checks=[];error=''
        try:checks=self.workers[current.task.owner](dispatched)
        except TaskConflict:raise
        except Exception as exc:error=f'{type(exc).__name__}: {exc}'[:4000]
        try:
            fingerprint=self.fingerprint()
            try:
                observed=Observation(revision=current.revision,fingerprint=fingerprint,checks=checks,error=error)
            except (ValueError,TypeError) as exc:
                observed=Observation(revision=current.revision,fingerprint=fingerprint,error='Rejected worker evidence: '+str(exc)[:3900])
        except Exception as exc:
            self.ledger.pause(dispatched,'Cannot inspect artifacts after worker: '+str(exc)[:1000],action_finished=True)
            return {}
        self.ledger.observe(dispatched,observed)
        return {}

    def _review(self,state):
        current=self.ledger.read(state['task_id'])
        dispatched=self.ledger.reserve_action(current,'senior_reviewer')
        child=self.ledger.create(Task(parent_id=current.task.id,owner='senior_reviewer',
            goal='Diagnose stalled work and propose a concrete recovery strategy without weakening required behavior.',
            inputs={'failed_task_id':current.task.id,'failed_revision':current.revision},
            required_checks=['recovery_plan_schema']),action_limit=1)
        child=self.ledger.reserve_action(self.ledger.start(child),'senior_reviewer')
        plan=None;error=''
        try:
            plan=RecoveryPlan.model_validate(self.reviewer(dispatched,child))
            if plan.owner not in self.workers:raise ValueError('Reviewer selected an unavailable worker')
            if plan.action=='request_input' and not current.task.allow_review_questions:raise ValueError('User-question authority was not delegated for this review')
            if plan.action=='retry' and plan.owner!=current.task.owner:raise ValueError('Ownership changes require reassign')
        except Exception as exc:error=f'{type(exc).__name__}: {exc}'[:4000]
        directory=self.ledger.store.path.parent/'task-reviews'/self.ledger.job_id
        directory.mkdir(parents=True,exist_ok=True);report=directory/(uuid4().hex+'.json')
        content=json.dumps({'task_id':current.task.id,'task_revision':current.revision,
            'review_task_id':child.task.id,'plan':plan.model_dump() if plan else None,
            'error':error,'scope':'Recovery proposal validation only; application success is not established.'},indent=2)
        report.write_text(content,encoding='utf-8',newline='\n');fingerprint=hashlib.sha256(report.read_bytes()).hexdigest()
        child=self.ledger.observe(child,Observation(revision=child.revision,fingerprint=fingerprint,
            checks=[CheckEvidence(check='recovery_plan_schema',exit_code=int(bool(error)),fingerprint=fingerprint,
                report=str(report.resolve()),summary=error or 'Proposal shape and role assignment validated; strategy effectiveness remains unproven.')]))
        if error:
            self.ledger.pause(child,'Review proposal was rejected; parent coordinator retains the failure evidence.')
            self.ledger.review_failed(dispatched,error)
        else:self.ledger.recover(dispatched,plan,set(self.workers))
        return {}
