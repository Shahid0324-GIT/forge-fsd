"""Persist explicit role handoffs without granting models additional capabilities."""
import hashlib
import json
from uuid import uuid4


def record_handoff(store, job_id, sender, recipient, summary, context, *, agents=None,task_id=None,parent_task_id=None):
    # This is the supplied context, not a model's assertion that it remembers it.
    raw = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if len(raw.encode('utf-8')) > 160000:
        raise ValueError('Agent handoff exceeds the saved context budget')
    directory = store.path.parent / 'handoffs' / job_id
    directory.mkdir(parents=True, exist_ok=True)
    handoff_id=uuid4().hex
    scope=context.get('file','')
    assigned_task_id=task_id
    task_id=assigned_task_id or hashlib.sha256(f'{job_id}:{recipient}:{scope}'.encode()).hexdigest()[:24]
    previous=getattr(agents,'invocation_context',{}) if agents is not None else {}
    parent=parent_task_id if assigned_task_id is not None else previous.get('task_id') if previous.get('actor')==sender else None
    path = directory / (handoff_id + '.json')
    identity={'version':1,'job_id':job_id,'handoff_id':handoff_id,'task_id':task_id,'parent_task_id':parent,
              'sender':sender,'recipient':recipient,'summary':summary,'file':scope,
              'context_sha256':hashlib.sha256(raw.encode('utf-8')).hexdigest()}
    path.write_text(json.dumps({**identity,'context':context}, ensure_ascii=False, indent=2), encoding='utf-8')
    payload = {**identity,
               'context_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
               'context_characters': len(raw), 'context_fields': list(context),
               'source_files': list(context.get('existing_source', {})) if 'current_source' not in context else [context['file'],*context.get('reference_only_source', {})],
               'context_omitted': context.get('context_omitted', []),
               'report': str(path.resolve())}
    store.event(job_id, 'AGENT_HANDOFF', payload, update_status=False)
    if agents is not None:
        agents.invocation_context={**previous,'job_id':job_id,'handoff_id':handoff_id,
            'task_id':task_id,'parent_task_id':parent,'actor':recipient,'file':scope,'context_sha256':identity['context_sha256']}
    return payload


def read_handoff(path, expected):
    packet=json.loads(path.read_text(encoding='utf-8'))
    raw=json.dumps(packet['context'],ensure_ascii=False,sort_keys=True,separators=(',',':'))
    if hashlib.sha256(raw.encode('utf-8')).hexdigest()!=expected.get('context_sha256'):
        raise ValueError('Saved handoff context differs from its recorded fingerprint')
    for field in ['sender','recipient','handoff_id','job_id']:
        if field in expected and packet.get(field)!=expected[field]:raise ValueError('Saved handoff identity differs from its event')
    return packet
