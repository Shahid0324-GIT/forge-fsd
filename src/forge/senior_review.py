"""Focused escalation role using the existing LangChain/Ollama adapter."""
import json
import hashlib
from typing import Annotated,Literal,Union

from pydantic import Field,RootModel,create_model

from forge.handoffs import record_handoff
from forge.check_context import observed_context
from forge.cycle_context import rejected_state_context
from forge.tasks import RecoveryPlan
from forge.provider_errors import ProviderResourceError
from forge.source_scope import scope_source,page_module


def scoped_review_context(context,failed,evidence):
    source=context.get('current_source')
    if not isinstance(source,dict) or not source or not all(isinstance(body,str) for body in source.values()):return context
    from forge.source_agent import diagnostic_context
    snapshot={path:{'content':body,'sha256':hashlib.sha256(body.encode('utf-8')).hexdigest()} for path,body in source.items()}
    design=context.get('approved_design',{});files=design.get('files',[]) if isinstance(design,dict) else []
    owners={file['path']:file['owner'] for file in files}
    seeds=list(dict.fromkeys(row['file'] for row in diagnostic_context(evidence,snapshot)))
    if not seeds:
        seeds=[path for path in source if owners.get(path)==failed.task.owner] or list(source)
        if evidence and any('browser_acceptance (exit' in check['summary'] for check in evidence.get('checks',[])):
            seeds=[path for path in seeds if page_module(path)] or seeds
    selected,omitted,inventory=scope_source(snapshot,seeds,owners or source)
    result={**context,'current_source':{path:packet['content'] for path,packet in selected.items()},
        'context_omitted':omitted,'source_inventory':[{**row,'owner':owners.get(row['file'])} for row in inventory]}
    if isinstance(design,dict):
        # Preserve app-owned architecture, assumptions and every criterion. File
        # ownership is represented in the inventory; execution reports describe
        # the checks actually run instead of repeating the original test proposal.
        result['approved_design']={key:value for key,value in design.items() if key not in {'files','test_strategy'}}
        result['context_omitted_fields']=[{'field':'approved_design.'+key,
            'sha256':hashlib.sha256(json.dumps(design[key],sort_keys=True).encode()).hexdigest(),
            'reason':'File ownership is in source_inventory; original test strategy is superseded by current execution evidence.'}
            for key in ('files','test_strategy') if key in design]
    return result


INSTRUCTION='''You are ForgeFSD's senior reviewer, called because ordinary recovery
has stalled. Diagnose the actual failure using the original task, supplied app-owned
artifacts, check evidence and previous attempts. The app's types, structure and behavior
are agent decisions; do not force a task-management template or discard requirements.
Identify whether the correction belongs to this worker or another registered owner.
Return a concrete next strategy and select its responsible registered owner. The
controller derives retry versus reassignment from that owner; the action label must
not prevent a valid ownership handoff. Request input only for an
actual missing business decision, access or platform capability, with a focused question.
Do not ask cosmetic or unnecessary technical questions. Do not repeat a failed strategy
without explaining the changed evidence or approach. Never weaken required checks,
claim that tests ran or passed, declare the app ready, expand tool permissions or approve
publishing/deployment. A proposed strategy will be checked by subsequent execution.
Return a short factual diagnosis and actionable strategy, not private reasoning.'''

INSTRUCTION+=''' The current_evidence packet is the present blocker. Earlier observations
and the previous unsuccessful strategy are history, not instructions. Verify the
diagnostic against current_source before recommending any symbol or import change.
If source no longer contains a previously broken symbol, that diagnosis is obsolete.
For a cycle, propose a correction addressing both failures instead of undoing the
latest edit and restoring a known failing workspace.'''
INSTRUCTION+=''' Browser failure_context.kind=text_mismatch identifies different rendered
text on an existing visible target. Inspect actual_text versus expected and the JSX
before blaming arithmetic or event handlers. Extra label text is part of innerText;
an accessible name does not replace that text. Never alter frozen expectations.'''


class SeniorReviewer:
    def __init__(self,agents,ledger,roles,*,context_loader=None,capabilities=None):
        if not roles:raise ValueError('Review needs registered worker roles')
        self.agents=agents;self.ledger=ledger;self.roles=sorted(roles);self.context_loader=context_loader
        self.capabilities=capabilities or {role:role for role in self.roles}
        if set(self.capabilities)!=set(self.roles):raise ValueError('Capabilities must describe the registered owners exactly')

    def __call__(self,failed,child):
        retry=create_model('WorkerRecovery',__base__=RecoveryPlan,action=(Literal['retry','reassign'],...),
            owner=(Literal[tuple(self.roles)],...),question=(Literal[''],'') )
        request=create_model('InputRecovery',__base__=RecoveryPlan,action=(Literal['request_input'],...),
            owner=(Literal[failed.task.owner],...),question=(str,Field(min_length=1,max_length=1000)))
        variants=[retry]
        if failed.task.allow_review_questions:variants.append(request)
        choice=variants[0] if len(variants)==1 else Annotated[Union[tuple(variants)],Field(discriminator='action')]
        schema=create_model('RecoveryDecision',__base__=RootModel[choice])
        remaining=5000;observations=[]
        for observed in [o for o in failed.observations if o.revision==failed.revision][-3:]:
            checks=[]
            for check in observed.checks:
                text=check.summary[:min(800,remaining)];remaining-=len(text)
                checks.append({'check':check.check,'exit_code':check.exit_code,'report':check.report,'summary':text})
            observations.append({'fingerprint':observed.fingerprint,'checks':checks,'error':observed.error[:1000]})
        history=[o for o in failed.observations if o.revision==failed.revision]
        current_fingerprint=history[-1].fingerprint if history else None
        latest=next((o for o in reversed(history) if o.checks and o.fingerprint==current_fingerprint),None)
        # Preserve old details in reports, not alongside the current debugging input.
        # The small model otherwise copies a previously suggested diagnosis verbatim.
        observations=[{'fingerprint':o['fingerprint'],'checks':[{'check':c['check'],'exit_code':c['exit_code'],'report':c['report']} for c in o['checks']]}
            for o in observations if o['fingerprint']==current_fingerprint]
        data={'current_evidence':observed_context(latest,self.ledger.store.path.parent) if latest else None,
            'rejected_state':rejected_state_context(failed,self.ledger.store.path.parent),
            'latest_tool_error':history[-1].error if history else '',
            'original_goal':failed.task.goal,'current_owner':failed.task.owner,
            'input_revision':failed.revision,'required_checks':failed.task.required_checks,
            'app_context':self.context_loader(failed) if self.context_loader else failed.task.inputs,
            'recent_observations':observations,'available_owners':self.roles,
            'owner_capabilities':self.capabilities,
            'review_questions_authorized':failed.task.allow_review_questions,
            'prior_strategy_supplied':failed.recovery is not None,
            'previous_review_error':failed.review_error,
            'context_limits':{'check_summaries_bounded':True,'full_evidence_in_referenced_reports':True}}
        data['app_context']=scoped_review_context(data['app_context'],failed,data['current_evidence'])
        if len(json.dumps(data,separators=(',',':')))>20000:
            raise ProviderResourceError('Senior-review context exceeds budget; supply the relevant artifacts instead of silently dropping requirements')
        previous_context=getattr(self.agents,'invocation_context',{})
        previous_activity=getattr(self.agents,'activity',None)
        if getattr(self.agents,'trace_directory',None) is None:
            self.agents.trace_directory=self.ledger.store.path.parent/'model-calls'/self.ledger.job_id
        try:
            record_handoff(self.ledger.store,self.ledger.job_id,'coordinator','senior_reviewer',
                'Diagnose stalled work and return a recovery proposal grounded in saved evidence.',data,
                agents=self.agents,task_id=child.task.id,parent_task_id=failed.task.id,task_state=child)
            self.agents.activity=lambda status,payload:self.ledger.store.event(self.ledger.job_id,status,payload,update_status=False)
            selected=self.agents.generate(schema,INSTRUCTION,data,coding=True).root
            if selected.action!='request_input':
                selected=selected.model_copy(update={'action':'retry' if selected.owner==failed.task.owner else 'reassign'})
            return RecoveryPlan.model_validate(selected.model_dump())
        finally:
            self.agents.invocation_context=previous_context;self.agents.activity=previous_activity
