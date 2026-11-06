"""Immutable model-call inputs and outcomes, linked to the actual handoff."""
import hashlib
import json
from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4


def begin_call(agent, schema, messages, attempt, coding):
    context=dict(getattr(agent,'invocation_context',{}))
    options={'num_ctx':32768 if coding else 16384,'num_predict':3000 if coding else 1600,'temperature':0}
    if getattr(agent,'model_name','') in {'groq:openai/gpt-oss-120b','groq:openai/gpt-oss-20b'}:
        options={'max_completion_tokens':3000 if coding else 1600,'temperature':0,
            'reasoning_effort':'medium','include_reasoning':False,'context_window':'provider-managed'}
    if getattr(agent,'model_name','').startswith('anthropic:'):
        options={'max_tokens':3000 if coding else 1600,'context_window':'provider-managed','request_allowance':4}
    return {'version':1, **context, 'call_id':uuid4().hex,
            'model':getattr(agent,'model_name','unknown'), 'schema':schema.__name__, 'attempt':attempt,
            'started_at':datetime.now(timezone.utc).isoformat(),
            'requested_options':options,
            'messages':list(messages), 'response_schema':schema.model_json_schema(),
            'input_sha256':hashlib.sha256(json.dumps(messages,separators=(',',':')).encode()).hexdigest(),
            '_timer':perf_counter()}


def finish_call(agent, packet, result=None, error=None):
    packet=dict(packet)
    packet['wall_seconds']=round(perf_counter()-packet.pop('_timer'),4)
    raw=(result or {}).get('raw')
    output=str(getattr(raw,'content',''))
    metadata=getattr(raw,'response_metadata',{})
    validation_error=str(error or (result or {}).get('parsing_error') or '')
    packet.update(output=output[:160000], output_truncated=len(output)>160000,
                  done_reason=metadata.get('done_reason'), provider_metadata=metadata,
                  validation_error=validation_error[-8000:],error_truncated=len(validation_error)>8000)
    packet['outcome']='ERROR' if validation_error else 'INCOMPLETE' if raw and metadata.get('done_reason')!='stop' else 'RETURNED'
    directory=getattr(agent,'trace_directory',None)
    if directory is not None:
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/(packet['call_id']+'.json')
        packet['report']=str(path.resolve())
        path.write_text(json.dumps(packet,indent=2,default=str),encoding='utf-8')
    route=metadata.get('groq_accounts')
    activity=getattr(agent,'activity',None)
    if activity and metadata.get('provider')=='groq' and isinstance(route,dict):
        activity('PROVIDER_ACCOUNT_ROUTED',{'call_id':packet['call_id'],'provider':'groq',**route,
            **({'report':packet['report']} if 'report' in packet else {})})
    return packet
