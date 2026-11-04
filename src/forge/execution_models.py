"""Explicit inference changes for paused approved work; app contracts stay unchanged."""
import hashlib
import json
from pathlib import Path

from forge.models import SUPPORTED_MODELS,job_model
from forge.tasks import TaskLedger
from forge.workspace import safe_path,source_fingerprint


def _fingerprint(binding):
    return hashlib.sha256(json.dumps(binding,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def authorized_models(job_id,store,review):
    models=[review['binding']['model']]
    for event in store.read(job_id)['events']:
        if event['status']!='INFERENCE_CHANGE_APPROVED':continue
        payload=event['payload'];binding=payload.get('binding',{})
        if binding.get('review_fingerprint')!=review['fingerprint']:continue
        if (binding.get('job_id')!=job_id or binding.get('previous_model')!=models[-1]
            or binding.get('model') not in SUPPORTED_MODELS or not payload.get('actor')
            or payload.get('model')!=binding['model'] or payload.get('fingerprint')!=_fingerprint(binding)):
            raise ValueError('Inference approval does not match the saved plan/model chain')
        models.append(binding['model'])
    return models


def execution_model(job_id,store,review):
    return authorized_models(job_id,store,review)[-1]


def model_change_snapshot(job_id,store,model,*,workspace_boundary=None):
    from forge.autonomous_review import approved_review
    if model not in SUPPORTED_MODELS:raise ValueError('Choose a supported inference model')
    record=store.read(job_id)
    if record['status'] not in {'AUTONOMOUS_BUILD_PAUSED','AUTONOMOUS_TEST_PAUSED'}:
        raise ValueError('Model changes require an idle saved build/QA pause')
    review=approved_review(job_id,store);previous=execution_model(job_id,store,review)
    if model==previous:raise ValueError('This model is already selected')
    ledger=TaskLedger(store,job_id)
    if any(task.inflight_role is not None for task in ledger.list()):raise ValueError('Reconcile in-flight work before changing inference')
    pending=next(e['payload'] for e in reversed(record['events']) if e['status']==record['status'])
    task=ledger.read(pending['task_id'])
    if task.status!='paused':raise ValueError('The saved task is no longer paused')
    boundary=Path(workspace_boundary) if workspace_boundary else Path(__file__).resolve().parents[2]/'workspace'
    root=safe_path(boundary,job_id);safe_path(root,'package.json')
    binding={'job_id':job_id,'review_fingerprint':review['fingerprint'],'previous_model':previous,'model':model,
        'paused_status':record['status'],'task_id':task.task.id,'revision':task.revision,'task_version':task.version,
        'source_fingerprint':source_fingerprint(root),'scope':'Remaining generation, QA and repair calls for this approved plan; previous source, contracts and evidence retain their recorded provenance.'}
    return {'binding':binding,'fingerprint':_fingerprint(binding)}


def approve_model_change(job_id,store,model,fingerprint,*,approved=False,actor='',workspace_boundary=None):
    if approved is not True or not actor:raise ValueError('Inference changes require explicit human approval and an actor')
    snapshot=model_change_snapshot(job_id,store,model,workspace_boundary=workspace_boundary)
    if snapshot['fingerprint']!=fingerprint:raise ValueError('Paused source/task changed; review the current inference change')
    store.event(job_id,'INFERENCE_CHANGE_APPROVED',{**snapshot,'model':model,'actor':actor},update_status=False)
    return store.read(job_id)
