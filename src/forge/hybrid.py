"""An explicit, persisted local-first routing policy for approved hybrid jobs."""
from forge.models import HYBRID_MODEL,job_model
from forge.tasks import TaskLedger,TaskConflict


LOCAL='qwen2.5-coder:7b'
CLOUD='groq:openai/gpt-oss-20b'
CLOUD_ROLES={'planner','senior_reviewer','acceptance_reviewer','requirements_reviewer','coverage_reviewer'}


class HybridRouter:
    def __init__(self,factory):self.factory=factory;self.clients={}

    def invoke(self,facade,method,*args,**kwargs):
        store=getattr(facade,'routing_store',None);context=getattr(facade,'invocation_context',{})
        if store is None or not context.get('task_id') or not context.get('task_revision'):
            raise ValueError('Hybrid inference requires a saved task/revision handoff')
        job=context['job_id'];record=store.read(job)
        if job_model(record)!=HYBRID_MODEL:raise ValueError('Hybrid routing was not selected for this job')
        ledger=TaskLedger(store,job);state=ledger.read(context['task_id'])
        if state.revision!=context['task_revision'] or state.version!=context.get('task_version') or state.status!='running' or state.inflight_role is None:
            raise TaskConflict('Hybrid handoff expired; rebuild current task context')
        related=[state]
        parent_revision=state.task.inputs.get('input_revision',state.task.inputs.get('failed_revision'))
        if state.task.parent_id and parent_revision is not None:
            parent=ledger.read(state.task.parent_id)
            if parent.revision!=parent_revision:raise TaskConflict('Hybrid parent context expired')
            related.append(parent)
        selected=LOCAL;reason='Local-first task'
        sticky=any(event['status']=='MODEL_ROUTED' and event['payload'].get('task_id')==state.task.id
            and event['payload'].get('revision')==state.revision and event['payload'].get('model')==CLOUD for event in record['events'])
        invalid=any(o.error.startswith(('ValueError: Invalid ','ValidationError:')) for task in related
            for o in task.observations if o.revision==task.revision)
        if context.get('actor') in CLOUD_ROLES:selected=CLOUD;reason='Planning or independent senior/quality review'
        elif sticky:selected=CLOUD;reason='Retain escalation for this task revision'
        elif invalid or any(task.no_progress>=2 for task in related):selected=CLOUD;reason='Observed invalid output or stalled task/parent'
        facade.last_call_identity={}
        store.event(job,'MODEL_ROUTED',{'policy':HYBRID_MODEL,'task_id':state.task.id,'revision':state.revision,
            'model':selected,'reason':reason,'context_sha256':context.get('context_sha256')},update_status=False)
        if selected not in self.clients:self.clients[selected]=self.factory(selected)
        child=self.clients[selected]
        child.trace_directory=getattr(facade,'trace_directory',None)
        child.invocation_context={**context,'inference_policy':HYBRID_MODEL,'routing_reason':reason}
        child.activity=getattr(facade,'activity',None)
        # One dispatch only. Failed local output must be observed by the coordinator
        # and receive fresh context before escalation. Provider limits never cause
        # a silent downgrade or a second request with potentially stale input.
        try:return getattr(child,method)(*args,**kwargs)
        finally:facade.last_call_identity=dict(getattr(child,'last_call_identity',{}))
