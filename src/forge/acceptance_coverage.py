"""Focused review of a QA agent's unsupported-capability claims; no app source input."""
import hashlib
import json

from pydantic import Field,model_validator

from forge.handoffs import record_handoff
from forge.tasks import CheckEvidence,Envelope,Observation,Task


class CoverageDecision(Envelope):
    can_check: bool
    reason: str = Field(min_length=1,max_length=600)
    strategy: list[str] = Field(max_length=6)

    @model_validator(mode='after')
    def actionable(self):
        if self.can_check and not self.strategy:raise ValueError('Supported coverage needs an executable action strategy')
        return self


INSTRUCTION='''Review one claimed unsupported acceptance criterion. Decide whether the
provided browser actions can check its observable behavior. You do not need app source
or implementation details: the app can be repaired to meet approved requirements.
Navigation to the same path AGAIN reloads within the SAME browser session, preserving
browser storage. For state that must reset on reload: visit, interact to change state,
visit the same path again, assert the expected initial visible value. This is supported.
Persistence after a SERVER/CONTAINER RESTART, security scans and cloud deployment are
not supported by these browser actions. Do not conflate a page reload with a server
restart. If supported give a short concrete strategy using available actions, not code.
If genuinely unsupported explain the missing capability. Never claim execution passed.'''


def review_coverage(ledger,state,agents,review,suite,authorize):
    if state.task.owner!='qa' or agents.model_name!=review['binding']['model']:raise ValueError('Coverage review requires the approved QA owner/model')
    corrections=[]
    for item in suite.uncovered:
        authorize();ledger.assert_active(state)
        path=ledger.store.path.parent/'acceptance-plans'/ledger.job_id/f'coverage-{state.task.id}-r{state.revision}-c{item.criterion}.json'
        if path.is_file():
            packet=json.loads(path.read_text(encoding='utf-8'));child=ledger.read(packet['task_id'])
            if child.status!='completed' or child.observations[-1].fingerprint!=hashlib.sha256(path.read_bytes()).hexdigest():
                raise ValueError('Coverage-review evidence changed')
            decision=CoverageDecision.model_validate(packet['decision'])
        else:
            child=ledger.reserve_action(ledger.start(ledger.create(Task(parent_id=state.task.id,owner='coverage_reviewer',
                goal='Review a claimed unsupported browser requirement.',inputs={'criterion':item.criterion,'review_fingerprint':review['fingerprint']},
                required_checks=['coverage_review']))),'coverage_reviewer')
            context={'criterion':review['draft']['acceptance_criteria'][item.criterion-1],'qa_claim':item.reason,
                'original_request':review['binding']['inputs']['original_request'],
                'human_clarifications':review['binding']['inputs'].get('human_clarifications',[]),
                'human_review_feedback':review['binding']['inputs'].get('human_review_feedback',[]),
                'available_actions':['visit/reload (same session)','click','fill','select','check',
                    'assert visible','assert text','assert form value','assert count','assert title']}
            previous=getattr(agents,'invocation_context',{});activity=getattr(agents,'activity',None)
            try:
                record_handoff(ledger.store,ledger.job_id,'acceptance_qa','coverage_reviewer',
                    'Check the unsupported claim against actual browser capabilities; no implementation is supplied.',context,
                    agents=agents,task_id=child.task.id,parent_task_id=state.task.id,task_state=child)
                agents.activity=lambda status,payload:ledger.store.event(ledger.job_id,status,payload,update_status=False)
                decision=CoverageDecision.model_validate(agents.generate(CoverageDecision,INSTRUCTION,context))
                authorize();ledger.assert_active(state)
                path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('x',encoding='utf-8',newline='\n') as out:out.write(json.dumps({'task_id':child.task.id,'decision':decision.model_dump()},indent=2))
                fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
                ledger.observe(child,Observation(revision=child.revision,fingerprint=fingerprint,checks=[CheckEvidence(
                    check='coverage_review',exit_code=0,fingerprint=fingerprint,report=str(path.resolve()),summary='Capability review proposal only; no app checks executed.')]))
            except Exception:
                ledger.pause(ledger.read(child.task.id),'Capability review needs inspection',action_finished=True)
                raise
            finally:agents.invocation_context=previous;agents.activity=activity
        if decision.can_check:corrections.append({'criterion':item.criterion,**decision.model_dump()})
    if corrections:raise ValueError('Coverage review found supported checks. Revise the proposal to exercise them: '+json.dumps(corrections))
