"""Persist explicit role handoffs without granting models additional capabilities."""
import hashlib
import json
from uuid import uuid4


def record_handoff(store, job_id, sender, recipient, summary, context):
    # This is the supplied context, not a model's assertion that it remembers it.
    raw = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    if len(raw.encode('utf-8')) > 160000:
        raise ValueError('Agent handoff exceeds the saved context budget')
    directory = store.path.parent / 'handoffs' / job_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (uuid4().hex + '.json')
    path.write_text(json.dumps({'sender': sender, 'recipient': recipient,
                               'summary': summary, 'context': context}, ensure_ascii=False, indent=2), encoding='utf-8')
    payload = {'sender': sender, 'recipient': recipient, 'summary': summary,
               'context_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
               'context_characters': len(raw), 'context_fields': list(context),
               'source_files': list(context.get('existing_source', {})) if 'current_source' not in context else [context['file'],*context.get('reference_only_source', {})],
               'context_omitted': context.get('context_omitted', []),
               'report': str(path.resolve())}
    store.event(job_id, 'AGENT_HANDOFF', payload, update_status=False)
    return payload
