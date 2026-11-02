"""Focused escalation role using the existing LangChain/Ollama adapter."""
import json
from typing import Annotated,Literal,Union

from pydantic import Field,RootModel,create_model

from forge.handoffs import record_handoff
from forge.tasks import RecoveryPlan


INSTRUCTION='''You are ForgeFSD's senior reviewer, called because ordinary recovery
has stalled. Diagnose the actual failure using the original task, supplied app-owned
artifacts, check evidence and previous attempts. The app's types, structure and behavior
are agent decisions; do not force a task-management template or discard requirements.
Identify whether the correction belongs to this worker or another registered owner.
Return a concrete next strategy with action=retry or reassign. Retry must keep the
current owner; reassignment must use an available owner. Request input only for an
actual missing business decision, access or platform capability, with a focused question.
Do not ask cosmetic or unnecessary technical questions. Do not repeat a failed strategy
without explaining the changed evidence or approach. Never weaken required checks,
claim that tests ran or passed, declare the app ready, expand tool permissions or approve
publishing/deployment. A proposed strategy will be checked by subsequent execution.
Return a short factual diagnosis and actionable strategy, not private reasoning.'''


class SeniorReviewer:
    def __init__(self,agents,ledger,roles,*,context_loader=None,capabilities=None):
        if not roles:raise ValueError('Review needs registered worker roles')
        self.agents=agents;self.ledger=ledger;self.roles=sorted(roles);self.context_loader=context_loader
        self.capabilities=capabilities or {role:role for role in self.roles}
        if set(self.capabilities)!=set(self.roles):raise ValueError('Capabilities must describe the registered owners exactly')

    def __call__(self,failed,child):
        retry=create_model('RetryRecovery',__base__=RecoveryPlan,action=(Literal['retry'],...),
            owner=(Literal[failed.task.owner],...),question=(Literal[''],'') )
        request=create_model('InputRecovery',__base__=RecoveryPlan,action=(Literal['request_input'],...),
            owner=(Literal[failed.task.owner],...),question=(str,Field(min_length=1,max_length=1000)))
        variants=[retry]
        if failed.task.allow_review_questions:variants.append(request)
        alternatives=tuple(role for role in self.roles if role!=failed.task.owner)
        if alternatives:
            variants.append(create_model('ReassignRecovery',__base__=RecoveryPlan,action=(Literal['reassign'],...),
                owner=(Literal[alternatives],...),question=(Literal[''],'')))
        choice=variants[0] if len(variants)==1 else Annotated[Union[tuple(variants)],Field(discriminator='action')]
        schema=create_model('RecoveryDecision',__base__=RootModel[choice])
        remaining=5000;observations=[]
        for observed in [o for o in failed.observations if o.revision==failed.revision][-3:]:
            checks=[]
            for check in observed.checks:
                text=check.summary[:min(800,remaining)];remaining-=len(text)
                checks.append({'check':check.check,'exit_code':check.exit_code,'report':check.report,'summary':text})
            observations.append({'fingerprint':observed.fingerprint,'checks':checks,'error':observed.error[:1000]})
        data={'original_goal':failed.task.goal,'current_owner':failed.task.owner,
            'input_revision':failed.revision,'required_checks':failed.task.required_checks,
            'app_context':self.context_loader(failed) if self.context_loader else failed.task.inputs,
            'recent_observations':observations,'available_owners':self.roles,
            'owner_capabilities':self.capabilities,
            'review_questions_authorized':failed.task.allow_review_questions,
            'previous_strategy':failed.recovery.model_dump() if failed.recovery else None,
            'previous_review_error':failed.review_error,
            'context_limits':{'check_summaries_bounded':True,'full_evidence_in_referenced_reports':True}}
        if len(json.dumps(data,separators=(',',':')))>20000:
            raise ValueError('Senior-review context exceeds budget; supply the relevant artifacts instead of silently dropping requirements')
        previous_context=getattr(self.agents,'invocation_context',{})
        previous_activity=getattr(self.agents,'activity',None)
        if getattr(self.agents,'trace_directory',None) is None:
            self.agents.trace_directory=self.ledger.store.path.parent/'model-calls'/self.ledger.job_id
        try:
            record_handoff(self.ledger.store,self.ledger.job_id,'coordinator','senior_reviewer',
                'Diagnose stalled work and return a recovery proposal grounded in saved evidence.',data,
                agents=self.agents,task_id=child.task.id,parent_task_id=failed.task.id)
            self.agents.activity=lambda status,payload:self.ledger.store.event(self.ledger.job_id,status,payload,update_status=False)
            return self.agents.generate(schema,INSTRUCTION,data,coding=True).root
        finally:
            self.agents.invocation_context=previous_context;self.agents.activity=previous_activity
