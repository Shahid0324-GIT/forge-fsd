"""Opt-in Groq chat adapter using LangChain and the standard-library HTTPS client."""
import http.client
import json
import os
from pathlib import Path
import time

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration,ChatResult
from langchain_core.runnables import RunnableLambda


GROQ_MODEL='groq:openai/gpt-oss-120b'
KEY_FILE=Path(__file__).resolve().parents[2]/'.env.local'


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

    @property
    def _llm_type(self):return 'forge-groq'

    @property
    def _identifying_params(self):return {'model_name':self.model_name,'temperature':self.temperature,'num_predict':self.num_predict}

    def _post(self,payload):
        connection=http.client.HTTPSConnection('api.groq.com',timeout=120)
        try:
            connection.request('POST','/openai/v1/chat/completions',body=json.dumps(payload).encode(),
                headers={'Authorization':'Bearer '+groq_key(),'Content-Type':'application/json'})
            response=connection.getresponse();raw=response.read(1_000_001)
            if len(raw)>1_000_000:raise ValueError('Groq response exceeds the output limit')
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
            'max_completion_tokens':self.num_predict,'reasoning_effort':'medium','include_reasoning':False}
        if stop:payload['stop']=stop
        if kwargs.get('response_schema') is not None:
            payload['response_format']={'type':'json_schema','json_schema':{'name':kwargs['schema_name'],
                'strict':False,'schema':kwargs['response_schema']}}
        status,retry,raw=self._post(payload)
        # One bounded provider wait, not a coding retry or a silent provider fallback.
        if status==429:
            try:delay=float(retry)
            except (ValueError,TypeError):delay=0
            if 0<delay<=60:
                time.sleep(delay);status,retry,raw=self._post(payload)
        if status!=200:
            suffix='; rate limit reached, wait and resume the saved operation' if status==429 else ''
            raise RuntimeError(f'Groq API returned HTTP {status}{suffix}')
        try:
            result=json.loads(raw);choice=result['choices'][0];content=choice['message']['content'];usage=result.get('usage',{})
            if not isinstance(content,str):raise ValueError('Missing text completion')
            message=AIMessage(content=content,response_metadata={'model':self.model_name,'provider':'groq',
                'done_reason':choice['finish_reason'],'request_id':result.get('id'),
                'max_completion_tokens':self.num_predict,'response_format':'json_schema_best_effort' if 'response_format' in payload else 'text'},
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
