"""Opt-in Groq chat adapter using LangChain and the standard-library HTTPS client."""
import http.client
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Literal
import time
from threading import Lock
from contextvars import ContextVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration,ChatResult
from langchain_core.runnables import RunnableLambda
from forge.provider_errors import ProviderResourceError
from forge.schema_wire import compact_titles


GROQ_MODEL='groq:openai/gpt-oss-120b'
GROQ_MODELS={GROQ_MODEL,'groq:openai/gpt-oss-20b'}
KEY_FILE=Path(__file__).resolve().parents[2]/'.env.local'
_TOKEN_BUDGETS={}
_REQUEST_LOCK=Lock()
_ACCOUNT_COOLDOWNS={}
_ACCOUNT_ROUTE=ContextVar('forge_groq_account_route',default=None)


class GeneratedJSONError(ValueError):
    """A rejected model candidate, never a successful chat response or quota error."""
    def __init__(self,candidate,metadata):
        super().__init__('Provider rejected generated JSON. Return one complete JSON object matching the supplied schema; preserve the requested behavior.')
        self.candidate=candidate;self.metadata=metadata


def _duration(value):
    """Parse only Groq's documented numeric duration format, never provider prose."""
    if not isinstance(value,str) or not re.fullmatch(r'(?:\d+(?:\.\d+)?[hms])+',value):return None
    return sum(float(number)*{'h':3600,'m':60,'s':1}[unit] for number,unit in re.findall(r'(\d+(?:\.\d+)?)([hms])',value))


def _strict_compatible(schema):
    """Use constrained decoding only for already closed, fully required schemas.

    Never rewrite optional fields, defaults or open application-owned dictionaries
    merely to satisfy a provider's stricter wire protocol.
    """
    def visit(node):
        if not isinstance(node,dict):return False
        if node.get('type')=='object' or 'properties' in node:
            properties=node.get('properties',{})
            if node.get('additionalProperties') is not False or set(node.get('required',[]))!=set(properties):return False
            if not all(visit(value) for value in properties.values()):return False
        for key in ('$defs','definitions'):
            if not all(visit(value) for value in node.get(key,{}).values()):return False
        if 'items' in node and not visit(node['items']):return False
        for key in ('anyOf','oneOf','allOf'):
            if not all(visit(value) for value in node.get(key,[])):return False
        return True
    return schema.get('type')=='object' and visit(schema)


def _object_root(schema):
    """JSON-object transport can represent object roots and object-only unions."""
    def visit(node,seen):
        if not isinstance(node,dict):return False
        if node.get('type')=='object':return True
        reference=node.get('$ref')
        if isinstance(reference,str) and reference.startswith('#/') and reference not in seen:
            target=schema
            try:
                for part in reference[2:].split('/'):target=target[part.replace('~1','/').replace('~0','~')]
            except (KeyError,TypeError):return False
            return visit(target,seen|{reference})
        variants=node.get('anyOf',node.get('oneOf'))
        return bool(variants) and all(visit(item,seen) for item in variants)
    return visit(schema,set())


def _local_provider_config():
    config={}
    if KEY_FILE.is_file():
        if KEY_FILE.stat().st_size>16384:raise ValueError('Local provider configuration exceeds its size limit')
        for line in KEY_FILE.read_text(encoding='utf-8-sig').splitlines():
            name,separator,value=line.strip().partition('=')
            if separator and (name in {'FORGE_GROQ_KEY_NAME','FORGE_GROQ_FALLBACK_KEY_NAME'} or re.fullmatch(r'GROQ_API_KEY(?:_[1-9][0-9]{0,2})?',name)):
                config[name]=value.strip().strip('\"\'')
    return config


def groq_key_name(config=None):
    config=_local_provider_config() if config is None else config
    name=os.environ.get('FORGE_GROQ_KEY_NAME',config.get('FORGE_GROQ_KEY_NAME','GROQ_API_KEY')).strip()
    if not re.fullmatch(r'GROQ_API_KEY(?:_[1-9][0-9]{0,2})?',name):
        raise ValueError('FORGE_GROQ_KEY_NAME must select GROQ_API_KEY or a numbered GROQ_API_KEY slot')
    return name


def groq_key():
    config=_local_provider_config();name=groq_key_name(config)
    key=os.environ.get(name,config.get(name,'')).strip()
    if not key or key=='your_key_here':raise ValueError(f'Save the selected {name} in .env.local or the environment before selecting Groq; no other key is used automatically')
    if any(char.isspace() for char in key):raise ValueError(f'{name} contains whitespace; check the local configuration')
    return key


def groq_accounts():
    """Only explicitly configured slots; never discover or cycle through keys."""
    config=_local_provider_config();primary=groq_key_name(config);accounts=[(primary,groq_key())]
    fallback=os.environ.get('FORGE_GROQ_FALLBACK_KEY_NAME',config.get('FORGE_GROQ_FALLBACK_KEY_NAME','')).strip()
    if fallback:
        if not re.fullmatch(r'GROQ_API_KEY(?:_[1-9][0-9]{0,2})?',fallback) or fallback==primary:
            raise ValueError('FORGE_GROQ_FALLBACK_KEY_NAME must select a different Groq credential slot')
        key=os.environ.get(fallback,config.get(fallback,'')).strip()
        if not key or key=='your_key_here' or any(char.isspace() for char in key):
            raise ValueError(f'Configure the selected fallback {fallback} before enabling Groq account fallback')
        if key==accounts[0][1]:raise ValueError('Groq account fallback requires two distinct credentials')
        accounts.append((fallback,key))
    return accounts


def _rate_facts(raw):
    """Only quota dimensions and numbers may survive a provider error body."""
    facts=[];dimension=re.search(rb'\b(tokens|requests) per (minute|day)\b',raw,re.I)
    if dimension:facts.append(dimension.group(0).decode('ascii').lower())
    for label in ('Limit','Used','Requested'):
        value=re.search(label.encode()+rb'\s+(\d+(?:\.\d+)?)',raw,re.I)
        if value:facts.append(label.lower()+' '+value.group(1).decode('ascii'))
    return ', '.join(facts)


def _account_metadata():
    route=_ACCOUNT_ROUTE.get()
    return {'groq_accounts':json.loads(json.dumps(route))} if route else {}


def _account_summary():
    route=_ACCOUNT_ROUTE.get()
    if not route or not route['fallback_enabled']:return ''
    return ' Accounts: '+', '.join(row['key_slot']+'='+str(row.get('http_status',row['outcome'])) for row in route['attempts'])+'.'


def _capacity_scope(model,key):
    # Never put credentials in LangChain model state, traces or public metadata.
    return model,hashlib.sha256(key.encode()).digest()


def groq_configured():
    try:groq_accounts();return True
    except (ValueError,OSError):return False


class GroqChat(BaseChatModel):
    model_name: str='openai/gpt-oss-120b'
    temperature: float=0
    num_predict: int=1600
    num_ctx: int=4096  # Existing worker option; the provider owns its context window.
    reasoning_effort: Literal['low','medium','high']='medium'

    @property
    def _llm_type(self):return 'forge-groq'

    @property
    def _identifying_params(self):return {'model_name':self.model_name,'temperature':self.temperature,'num_predict':self.num_predict,'reasoning_effort':self.reasoning_effort}

    def _post(self,payload):
        # Copies with different completion budgets share the model's last capacity
        # receipt. The dashboard has one active worker; a restarted worker can still
        # encounter 429 and retains the existing bounded provider retry below.
        with _REQUEST_LOCK:
            try:accounts=groq_accounts()
            except (ValueError,OSError):
                raise ProviderResourceError('Groq account configuration is invalid or unavailable; check the explicitly configured credential slots before resuming.') from None
            enabled=len(accounts)>1
            route={'fallback_enabled':enabled,'attempts':[]};_ACCOUNT_ROUTE.set(route)
            last=None
            for slot,key in accounts:
                scope=_capacity_scope(self.model_name,key)
                cooldown=_ACCOUNT_COOLDOWNS.get(scope) if enabled else None
                if cooldown and cooldown[0]>time.monotonic():
                    route['attempts'].append({'key_slot':slot,'http_status':429,'outcome':'cooldown'})
                    last=(429,str(cooldown[0]-time.monotonic()),cooldown[1]);continue
                try:status,retry,raw=self._budgeted_post(payload,key=key)
                except ProviderResourceError as exc:
                    route['attempts'].append({'key_slot':slot,'outcome':'resource_pause'})
                    raise ProviderResourceError(str(exc)+_account_summary()) from None
                route['key_slot']=slot
                route['attempts'].append({'key_slot':slot,'http_status':status,'outcome':'rate_limited' if status==429 else 'returned'})
                last=(status,retry,raw)
                if status!=429:return last
                if enabled:
                    try:delay=float(retry)
                    except (TypeError,ValueError):delay=60
                    # A missing reset time is a short reprobe cooldown, not a
                    # claim that the daily quota will reset in sixty seconds.
                    if not 0<delay<=86400:delay=60
                    _ACCOUNT_COOLDOWNS[scope]=(time.monotonic()+delay,_rate_facts(raw).encode('ascii'))
            return last

    def _budgeted_post(self,payload,*,key=None):
        key=groq_key() if key is None else key;scope=_capacity_scope(self.model_name,key)
        body=json.dumps(payload).encode();budget=_TOKEN_BUDGETS.get(scope)
        if budget:
            remaining,limit,deadline=budget
            # UTF-8 bytes are a conservative upper bound, not a tokenizer estimate.
            # Large requests wait for refill; small requests can use known capacity.
            required=min(limit,len(body)+payload.get('max_completion_tokens',self.num_predict))
            delay=deadline-time.monotonic()
            if remaining<required and delay>0:
                if delay>60:raise ProviderResourceError('Groq token refill exceeds the bounded wait. Resume after the provider capacity resets.')
                time.sleep(delay)
        connection=http.client.HTTPSConnection('api.groq.com',timeout=120)
        try:
            connection.request('POST','/openai/v1/chat/completions',body=body,
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            response=connection.getresponse();raw=response.read(1_000_001)
            if len(raw)>1_000_000:raise ValueError('Groq response exceeds the output limit')
            try:
                remaining=int(response.getheader('x-ratelimit-remaining-tokens'))
                limit=int(response.getheader('x-ratelimit-limit-tokens'))
                reset=_duration(response.getheader('x-ratelimit-reset-tokens'))
                if 0<=remaining<=limit and limit>0 and reset is not None:
                    _TOKEN_BUDGETS[scope]=(remaining,limit,time.monotonic()+reset)
            except (ValueError,TypeError):pass
            return response.status,response.getheader('Retry-After'),raw
        except (OSError,http.client.HTTPException):
            raise ProviderResourceError('Groq HTTPS request failed; check connectivity and resume the saved operation. No app defect inferred.') from None
        finally:connection.close()

    def _generate(self,messages,stop=None,run_manager=None,**kwargs):
        _ACCOUNT_ROUTE.set(None)
        roles={'human':'user','ai':'assistant','system':'system'}
        wire=[]
        for message in messages:
            if message.type not in roles or not isinstance(message.content,str):raise ValueError('Groq adapter accepts text chat messages only')
            wire.append({'role':roles[message.type],'content':message.content})
        payload={'model':self.model_name,'messages':wire,'temperature':self.temperature,
            'max_completion_tokens':self.num_predict,'reasoning_effort':self.reasoning_effort,'include_reasoning':False}
        if stop:payload['stop']=stop
        if kwargs.get('response_schema') is not None:
            wire_schema=compact_titles(kwargs['response_schema'])
            strict=self.model_name in {'openai/gpt-oss-20b','openai/gpt-oss-120b'} and _strict_compatible(wire_schema)
            if not strict and _object_root(wire_schema):
                # Keep optional/default/open fields intact. The same Pydantic
                # model remains authoritative; no retry or schema relaxation.
                payload['response_format']={'type':'json_object'}
                payload['messages']=[*wire,{'role':'system','content':
                    'Return ONE JSON object instance conforming to the following JSON Schema. '
                    'Return the instance, not the schema. Preserve every required field and constraint. '
                    'Do not include markdown or explanation. JSON Schema: '+json.dumps(wire_schema,separators=(',',':'))}]
            else:
                payload['response_format']={'type':'json_schema','json_schema':{'name':kwargs['schema_name'],
                    'strict':strict,'schema':wire_schema}}
        status,retry,raw=self._post(payload)
        # A size cap may include the output reserve. Try one numeric adjustment,
        # never truncating the prompt/schema or assuming that it must fit.
        # One adjustment only; a genuinely oversized input remains a saved pause.
        if status==413:
            limits=re.search(rb'Limit\s+(\d+).*?Requested\s+(\d+)',raw,re.I|re.S)
            if limits:
                limit,requested=map(int,limits.groups())
                fitted=self.num_predict-(requested-limit)-64
                if requested>limit>0 and 1024<=fitted<self.num_predict:
                    payload={**payload,'max_completion_tokens':fitted}
                    status,retry,raw=self._post(payload)
        # One bounded provider wait, not a coding retry or a silent provider fallback.
        if status==429 and not (_ACCOUNT_ROUTE.get() or {}).get('fallback_enabled') and not re.search(rb'\b(?:tokens|requests) per day\b',raw,re.I):
            try:delay=float(retry)
            except (ValueError,TypeError):delay=0
            if 0<delay<=60:
                time.sleep(delay);status,retry,raw=self._post(payload)
        if status!=200:
            if status==400 and kwargs.get('response_schema') is not None:
                try:rejected=json.loads(raw).get('error',{})
                except (ValueError,AttributeError):rejected={}
                if isinstance(rejected,dict) and rejected.get('code')=='json_validate_failed':
                    # Recover only the bounded, explicitly named model candidate,
                    # never provider prose/account identifiers. It is NOT an
                    # accepted completion, even if local parsing would succeed.
                    candidate=rejected.get('failed_generation','')
                    if (not isinstance(candidate,str) or len(candidate)>16000
                        or not candidate.lstrip().startswith('{') or re.search(r'gsk_[A-Za-z0-9_-]{20,}',candidate)):
                        candidate=''
                    raise GeneratedJSONError(candidate,{'model':self.model_name,'provider':'groq',
                        **_account_metadata(),
                        'done_reason':'provider_json_rejected','http_status':400,'json_output_rejected':True,
                        'max_completion_tokens':payload['max_completion_tokens'],
                        'completion_budget_adjusted':payload['max_completion_tokens']!=self.num_predict})
            if status in {401,403,413,429}:
                detail=''
                if status==413:
                    # Only numeric limits are retained; never echo provider bodies,
                    # account IDs, source, or credentials into failure summaries.
                    limits=re.search(rb'Limit\s+(\d+).*?Requested\s+(\d+)',raw,re.I|re.S)
                    if limits:detail=f' (token limit {int(limits[1])}, requested {int(limits[2])})'
                if status==429:
                    # Persist actionable capacity facts, never arbitrary provider
                    # prose (which can contain organization IDs or echoed input).
                    facts=_rate_facts(raw)
                    if facts:detail=' ('+facts+')'
                reason={401:'credential rejected',403:'model access denied',413:'request too large',429:'rate limit reached'}[status]
                raise ProviderResourceError(f'Groq HTTP {status}: {reason}{detail}. Provider resource pause; no app defect inferred.'+_account_summary())
            # Provider failures must not consume app-repair/senior-review loops.
            # Retain allowlisted categories, never echoed prompts or credentials.
            detail=''
            try:
                error=json.loads(raw).get('error',{})
                if isinstance(error,dict):
                    categories={'json_validate_failed':'generated JSON failed provider validation',
                        'tool_use_failed':'tool output failed provider validation',
                        'invalid_request_error':'invalid provider request',
                        'context_length_exceeded':'context length exceeded',
                        'invalid_schema':'request schema rejected'}
                    category=categories.get(error.get('code')) or categories.get(error.get('type'))
                    fields=[name for name in ('response_format','reasoning_effort','max_completion_tokens')
                        if isinstance(error.get('message'),str) and name in error['message']]
                    facts=([category] if category else [])+(['request field '+name for name in fields])
                    if facts:detail=' ('+', '.join(facts)+')'
            except (ValueError,TypeError,AttributeError):pass
            raise ProviderResourceError(f'Groq HTTP {status}: provider request rejected{detail}. '
                'Saved work retained; no app defect inferred.'+_account_summary())
        try:
            result=json.loads(raw);choice=result['choices'][0];content=choice['message']['content'];usage=result.get('usage',{})
            if not isinstance(content,str):raise ValueError('Missing text completion')
            message=AIMessage(content=content,response_metadata={'model':self.model_name,'provider':'groq',
                **_account_metadata(),
                'done_reason':choice['finish_reason'],'request_id':result.get('id'),
                'max_completion_tokens':payload['max_completion_tokens'],'reasoning_effort':self.reasoning_effort,
                'completion_budget_adjusted':payload['max_completion_tokens']!=self.num_predict,
                'schema_annotations':'titles_omitted_v1' if kwargs.get('response_schema') is not None else None,
                'response_format':('json_object_local_validation' if payload['response_format']['type']=='json_object' else
                    'json_schema_strict' if payload['response_format']['json_schema']['strict'] else 'json_schema_best_effort') if 'response_format' in payload else 'text'},
                usage_metadata={'input_tokens':usage.get('prompt_tokens',0),'output_tokens':usage.get('completion_tokens',0),
                    'total_tokens':usage.get('total_tokens',0)})
        except (ValueError,KeyError,IndexError,TypeError):raise ProviderResourceError('Groq returned an invalid chat envelope; provider response unavailable, no app defect inferred.'+_account_summary()) from None
        return ChatResult(generations=[ChatGeneration(message=message)])

    def with_structured_output(self,schema,*,method='json_schema',include_raw=False,**kwargs):
        if method!='json_schema':raise ValueError('Only JSON-schema structured output is enabled')
        def generate(messages):
            try:raw=self.invoke(messages,response_schema=schema.model_json_schema(),schema_name=schema.__name__)
            except GeneratedJSONError as rejected:
                raw=AIMessage(content=rejected.candidate,response_metadata=rejected.metadata)
            try:
                if raw.response_metadata.get('json_output_rejected'):
                    raise ValueError('Provider rejected generated JSON. Return one complete JSON object matching the supplied schema; preserve the requested behavior.')
                parsed=schema.model_validate_json(raw.content);error=None
            except ValueError as exc:parsed=None;error=exc
            if include_raw:return {'raw':raw,'parsed':parsed,'parsing_error':error}
            if error:raise error
            return parsed
        return RunnableLambda(generate)
