"""Explicit, request-capped Claude recovery adapter; no automatic paid fallback."""
import http.client
import json
import os
from pathlib import Path
from threading import Lock

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration,ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import PrivateAttr

from forge.provider_errors import ProviderResourceError

KEY_FILE=Path(__file__).resolve().parents[2]/'.env.local'
CLAUDE_MODEL='anthropic:claude-opus-5-5'

def anthropic_key():
    key=os.environ.get('ANTHROPIC_API_KEY','').strip()
    if not key and KEY_FILE.is_file():
        if KEY_FILE.stat().st_size>16384:raise ValueError('Local provider configuration exceeds its size limit')
        for line in KEY_FILE.read_text(encoding='utf-8-sig').splitlines():
            name,separator,value=line.strip().partition('=')
            if separator and name=='ANTHROPIC_API_KEY':key=value.strip().strip('\"\'')
    if not key or any(c.isspace() for c in key):raise ValueError('Configure a valid ANTHROPIC_API_KEY locally')
    return key

class CallBudget:
    def __init__(self):self.used=0;self.lock=Lock()
    def reserve(self):
        with self.lock:
            if self.used>=4:raise ProviderResourceError('Claude recovery allowance exhausted (4 requests per worker). Inspect the saved checkpoint before authorizing further use.')
            self.used+=1

class AnthropicChat(BaseChatModel):
    model_name:str='claude-opus-5-5'
    num_predict:int=1600
    num_ctx:int=4096
    temperature:float=0
    _budget:CallBudget=PrivateAttr(default_factory=CallBudget)

    @property
    def _llm_type(self):return 'forge-anthropic'
    @property
    def _identifying_params(self):return {'model_name':self.model_name,'num_predict':self.num_predict}

    def _post(self,payload):
        connection=http.client.HTTPSConnection('api.anthropic.com',timeout=120)
        try:
            connection.request('POST','/v1/messages',body=json.dumps(payload).encode(),headers={
                'x-api-key':anthropic_key(),'anthropic-version':'2023-06-01','Content-Type':'application/json'})
            response=connection.getresponse();raw=response.read(1_000_001)
            if len(raw)>1_000_000:raise ValueError('Claude response exceeds the output limit')
            return response.status,raw
        except (OSError,http.client.HTTPException):
            raise ProviderResourceError('Claude HTTPS request failed; inspect and resume the saved operation') from None
        finally:connection.close()

    def _generate(self,messages,stop=None,run_manager=None,**kwargs):
        system=[];wire=[]
        for message in messages:
            if not isinstance(message.content,str):raise ValueError('Claude accepts text messages only')
            if message.type=='system':system.append(message.content)
            elif message.type in {'human','ai'}:wire.append({'role':'user' if message.type=='human' else 'assistant','content':message.content})
            else:raise ValueError('Unsupported Claude message role')
        payload={'model':self.model_name,'max_tokens':min(self.num_predict,3000),'messages':wire,'system':'\n\n'.join(system),
            'output_config':{'effort':'low'}}
        if stop:payload['stop_sequences']=stop
        # This schema-only tool returns data. It grants no execution capability.
        if kwargs.get('response_schema') is not None:
            # Tool inputs must be objects. RootModel unions remain unchanged
            # inside a transport envelope; hoist definitions so local refs retain
            # their original meaning. The app-owned schema is validated below.
            schema=dict(kwargs['response_schema']);definitions=schema.pop('$defs',None)
            envelope={'type':'object','properties':{'result':schema},'required':['result'],'additionalProperties':False}
            if definitions is not None:envelope['$defs']=definitions
            payload['tools']=[{'name':'emit_result','description':'Return the requested structured result inside the result property.','input_schema':envelope}]
            # Opus 5.5 rejects forced tool choice. Keep the original schema and
            # validate locally; accept exactly one named schema result only.
            payload['tool_choice']={'type':'auto','disable_parallel_tool_use':True}
            payload['system']+='\nReturn your complete answer by calling emit_result exactly once. Do not answer with prose.'
        self._budget.reserve()
        status,raw=self._post(payload)
        if status!=200:raise ProviderResourceError(f'Claude HTTP {status}; provider request paused. No app defect inferred.')
        try:
            result=json.loads(raw);reason=result['stop_reason'];blocks=result['content'];usage=result.get('usage',{})
            if 'tools' in payload:
                calls=[b for b in blocks if b.get('type')=='tool_use' and b.get('name')=='emit_result']
                if reason!='tool_use' or len(calls)!=1:raise ProviderResourceError('Claude structured result incomplete; no proposal accepted')
                content=json.dumps(calls[0]['input']['result'])
            else:
                if reason!='end_turn':raise ProviderResourceError('Claude source incomplete; no file written')
                content=''.join(b['text'] for b in blocks if b.get('type')=='text')
            if not content:raise ValueError('Empty response')
        except (KeyError,TypeError,ValueError):raise ValueError('Claude returned an invalid response') from None
        message=AIMessage(content=content,response_metadata={'provider':'anthropic','model':self.model_name,'done_reason':'stop',
            'provider_stop_reason':reason,'max_tokens':payload['max_tokens'],'requests_used':self._budget.used,'request_allowance':4},
            usage_metadata={'input_tokens':usage.get('input_tokens',0),'output_tokens':usage.get('output_tokens',0),
                'total_tokens':usage.get('input_tokens',0)+usage.get('output_tokens',0)})
        return ChatResult(generations=[ChatGeneration(message=message)])

    def with_structured_output(self,schema,*,method='json_schema',include_raw=False,**kwargs):
        if method!='json_schema':raise ValueError('Only schema-validated structured output is enabled')
        def generate(messages):
            raw=self.invoke(messages,response_schema=schema.model_json_schema())
            try:parsed=schema.model_validate_json(raw.content);error=None
            except ValueError as exc:parsed=None;error=exc
            if include_raw:return {'raw':raw,'parsed':parsed,'parsing_error':error}
            if error:raise error
            return parsed
        return RunnableLambda(generate)
