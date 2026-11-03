"""Review clarification ownership before asking a user to design implementation."""
import hashlib
import json
from typing import Literal

from pydantic import Field

from forge.handoffs import record_handoff
from forge.tasks import CheckEvidence,Envelope,Observation,Task


class ClarificationReview(Envelope):
    disposition: Literal['ask_user','delegate_to_planner']
    requirement_quote: str = Field(min_length=1,max_length=1000)
    reason: str = Field(min_length=1,max_length=600)


INSTRUCTION='''Review who owns the proposed clarification questions. This is a bounded
Next.js app builder. The planner owns implementation decisions: API/request-response
design, project layout, types, files, server/client boundaries and how to implement
the already stated persistence choice. Questions asking the user to design these
belong to delegate_to_planner, not ask_user. Review feedback asking the planner to
explain its design is not a missing user decision. Choose ask_user only for a genuinely
missing business requirement or an unsupported capability that the user must resolve
(authentication, payments, external services or extra packages). Do not infer such a
blocker when it was not requested. Already associated clarification answers are user
decisions; questions and rejected-proposal descriptions are not desired behavior.
If any genuinely unresolved business blocker remains, use ask_user; do not hide it by
delegating technical choices. Quote an exact excerpt from supplied original request,
review feedback or human answers supporting your decision. Return concise evidence
and disposition, not private reasoning or claims that an app works.'''


def review_clarification(ledger,state,agents,data,proposed):
    ledger.assert_active(state)
    child=ledger.reserve_action(ledger.start(ledger.create(Task(parent_id=state.task.id,owner='intake_reviewer',
        goal='Decide whether proposed clarification belongs to the user or the planner.',
        inputs={'parent_revision':state.revision},required_checks=['clarification_review']))),'intake_reviewer')
    context={**data,'proposed_clarification':proposed.model_dump()}
    previous=getattr(agents,'invocation_context',{});activity=getattr(agents,'activity',None)
    try:
        if len(json.dumps(context,separators=(',',':')))>18000:raise ValueError('Clarification review exceeds context budget')
        record_handoff(ledger.store,ledger.job_id,'requirements','intake_reviewer',
            'Check question ownership before asking the user; implementation choices belong to the planner.',context,
            agents=agents,task_id=child.task.id,parent_task_id=state.task.id)
        agents.activity=lambda status,payload:ledger.store.event(ledger.job_id,status,payload,update_status=False)
        decision=ClarificationReview.model_validate(agents.generate(ClarificationReview,INSTRUCTION,context))
        ledger.assert_active(state)
        texts=[data['application_request'],*data.get('human_review_feedback',[]),
            json.dumps(data.get('human_clarifications',[]),ensure_ascii=False)]
        if not any(decision.requirement_quote.casefold() in text.casefold() for text in texts):
            raise ValueError('Clarification ownership review must quote the actual request or answers')
        path=ledger.store.path.parent/'intake-reviews'/ledger.job_id/(child.task.id+'.json');path.parent.mkdir(parents=True,exist_ok=True)
        packet={'task_id':child.task.id,'parent_task_id':state.task.id,'parent_revision':state.revision,
            'proposed_clarification':proposed.model_dump(),'decision':decision.model_dump(),
            'scope':'Question ownership proposal only; no human answer or application success is implied.'}
        path.write_text(json.dumps(packet,indent=2),encoding='utf-8');digest=hashlib.sha256(path.read_bytes()).hexdigest()
        ledger.observe(child,Observation(revision=child.revision,fingerprint=digest,checks=[CheckEvidence(
            check='clarification_review',exit_code=0,fingerprint=digest,report=str(path.resolve()),
            summary='Clarification ownership grounded in current request; not an app correctness check.')]))
        return decision
    except Exception:
        ledger.pause(ledger.read(child.task.id),'Clarification review needs inspection',action_finished=True)
        raise
    finally:agents.invocation_context=previous;agents.activity=activity
