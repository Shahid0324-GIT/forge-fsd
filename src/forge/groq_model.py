"""Opt-in Groq chat adapter using LangChain and the standard-library HTTPS client."""
import http.client
import json
import os
import re
from pathlib import Path
from typing import Literal
import time
from threading import Lock

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration,ChatResult
from langchain_core.runnables import RunnableLambda
from forge.provider_errors import ProviderResourceError


GROQ_MODEL='groq:openai/gpt-oss-120b'
GROQ_MODELS={GROQ_MODEL,'groq:openai/gpt-oss-20b'}
KEY_FILE=Path(__file__).resolve().parents[2]/'.env.local'
_TOKEN_BUDGETS={}
_REQUEST_LOCK=Lock()


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


def groq_key():
    key=os.environ.get('GROQ_API_KEY','').strip()
    if not key and KEY_FILE.is_file():
        if KEY_FILE.stat().st_size>16384:raise ValueError('Local provider configuration exceeds its size limit')
        for line in KEY_FILE.read_text(encoding='utf-8-sig').splitlines():
            name,separator,value=line.strip().partition('=')
            if separator and name=='GROQ_API_KEY':key=value.strip().strip('\"\'')
    if not key or key=='your_key_here':raise ValueError('Save GROQ_API_KEY in .env.local or the environment before selecting Groq')
    if any(char.isspace() for char in key):raise ValueError('GROQ_API_KEY contains whitespace; check the local configuration')
    return key


def groq_configured():
    try:groq_key();return True
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
        with _REQUEST_LOCK:return self._budgeted_post(payload)

    def _budgeted_post(self,payload):
        body=json.dumps(payload).encode();budget=_TOKEN_BUDGETS.get(self.model_name)
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
                headers={'Authorization':'Bearer '+groq_key(),'Content-Type':'application/json'})
            response=connection.getresponse();raw=response.read(1_000_001)
            if len(raw)>1_000_000:raise ValueError('Groq response exceeds the output limit')
            try:
                remaining=int(response.getheader('x-ratelimit-remaining-tokens'))
                limit=int(response.getheader('x-ratelimit-limit-tokens'))
                reset=_duration(response.getheader('x-ratelimit-reset-tokens'))
                if 0<=remaining<=limit and limit>0 and reset is not None:
                    _TOKEN_BUDGETS[self.model_name]=(remaining,limit,time.monotonic()+reset)
            except (ValueError,TypeError):pass
            return response.status,response.getheader('Retry-After'),raw
        except (OSError,http.client.HTTPException):
            raise RuntimeError('Groq HTTPS request failed; check connectivity and resume the saved operation') from None
        finally:connection.close()

    def _generate(self,messages,stop=None,run_manager=None,**kwargs):
        roles={'human':'user','ai':'assistant','system':'system'}
        wire=[]
        for message in messages:
            if message.type not in roles or not isinstance(message.content,str):raise ValueError('Groq adapter accepts text chat messages only')
            wire.append({'role':roles[message.type],'content':message.content})
        payload={'model':self.model_name,'messages':wire,'temperature':self.temperature,
            'max_completion_tokens':self.num_predict,'reasoning_effort':self.reasoning_effort,'include_reasoning':False}
        if stop:payload['stop']=stop
        if kwargs.get('response_schema') is not None:
            strict=self.model_name in {'openai/gpt-oss-20b','openai/gpt-oss-120b'} and _strict_compatible(kwargs['response_schema'])
            if not strict and _object_root(kwargs['response_schema']):
                # Keep optional/default/open fields intact. The same Pydantic
                # model remains authoritative; no retry or schema relaxation.
                payload['response_format']={'type':'json_object'}
                payload['messages']=[*wire,{'role':'system','content':
                    'Return ONE JSON object instance conforming to the following JSON Schema. '
                    'Return the instance, not the schema. Preserve every required field and constraint. '
                    'Do not include markdown or explanation. JSON Schema: '+json.dumps(kwargs['response_schema'],separators=(',',':'))}]
            else:
                payload['response_format']={'type':'json_schema','json_schema':{'name':kwargs['schema_name'],
                    'strict':strict,'schema':kwargs['response_schema']}}
        status,retry,raw=self._post(payload)
        # The provider cap includes reserved completion tokens. Fit that reserve
        # from its exact numeric receipt, never by truncating the prompt/schema.
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
        if status==429 and not re.search(rb'\b(?:tokens|requests) per day\b',raw,re.I):
            try:delay=float(retry)
            except (ValueError,TypeError):delay=0
            if 0<delay<=60:
                time.sleep(delay);status,retry,raw=self._post(payload)
        if status!=200:
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
                    facts=[]
                    dimension=re.search(rb'\b(tokens|requests) per (minute|day)\b',raw,re.I)
                    if dimension:facts.append(dimension.group(0).decode('ascii').lower())
                    for label in ('Limit','Used','Requested'):
                        value=re.search(label.encode()+rb'\s+(\d+(?:\.\d+)?)',raw,re.I)
                        if value:facts.append(label.lower()+' '+value.group(1).decode('ascii'))
                    if facts:detail=' ('+', '.join(facts)+')'
                reason={401:'credential rejected',403:'model access denied',413:'request too large',429:'rate limit reached'}[status]
                raise ProviderResourceError(f'Groq HTTP {status}: {reason}{detail}. Provider resource pause; no app defect inferred.')
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
                'Saved work retained; no app defect inferred.')
        try:
            result=json.loads(raw);choice=result['choices'][0];content=choice['message']['content'];usage=result.get('usage',{})
            if not isinstance(content,str):raise ValueError('Missing text completion')
            message=AIMessage(content=content,response_metadata={'model':self.model_name,'provider':'groq',
                'done_reason':choice['finish_reason'],'request_id':result.get('id'),
                'max_completion_tokens':payload['max_completion_tokens'],'reasoning_effort':self.reasoning_effort,
                'completion_budget_adjusted':payload['max_completion_tokens']!=self.num_predict,
                'response_format':('json_object_local_validation' if payload['response_format']['type']=='json_object' else
                    'json_schema_strict' if payload['response_format']['json_schema']['strict'] else 'json_schema_best_effort') if 'response_format' in payload else 'text'},
                usage_metadata={'input_tokens':usage.get('prompt_tokens',0),'output_tokens':usage.get('completion_tokens',0),
                    'total_tokens':usage.get('total_tokens',0)})
        except (ValueError,KeyError,IndexError,TypeError):raise ValueError('Groq returned an invalid chat response') from None
        return ChatResult(generations=[ChatGeneration(message=message)])

    def with_structured_output(self,schema,*,method='json_schema',include_raw=False,**kwargs):
        if method!='json_schema':raise ValueError('Only JSON-schema structured output is enabled')
        def generate(messages):
            raw=self.invoke(messages,response_schema=schema.model_json_schema(),schema_name=schema.__name__)
            try:parsed=schema.model_validate_json(raw.content);error=None
            except ValueError as exc:parsed=None;error=exc
            if include_raw:return {'raw':raw,'parsed':parsed,'parsing_error':error}
            if error:raise error
            return parsed
        return RunnableLambda(generate)
