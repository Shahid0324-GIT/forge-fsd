import json
from types import SimpleNamespace

import pytest

from forge.agents import OllamaAgents
from forge.source_text import decode_source
from forge.provider_errors import ProviderResourceError


@pytest.mark.parametrize('fenced',[False,True])
def test_source_quotes_backslashes_and_unicode_are_preserved(fenced):
    source='export default function Page(){return <label htmlFor="title">Café \\ path</label>}'
    assert decode_source('```tsx\n'+source+'\n```' if fenced else source)==source+'\n'


@pytest.mark.parametrize('text',['','   ','```tsx\nunfinished','```tsx\na\n```\n```tsx\nb\n```','a'*24001,[]])
def test_ambiguous_incomplete_empty_or_oversized_transport_is_rejected(text):
    with pytest.raises(ValueError):decode_source(text)


def test_normalized_source_stays_within_the_writer_budget():
    assert len(decode_source('x'*23999))==24000
    with pytest.raises(ValueError):decode_source('x'*24000)


class Model:
    def __init__(self,content,reason='stop'):self.content=content;self.reason=reason;self.messages=None
    def model_copy(self,*,update):
        assert update=={'num_predict':6000,'num_ctx':32768};return self
    def with_structured_output(self,*_,**__):raise AssertionError('Source must not use JSON-constrained generation')
    def invoke(self,messages):
        self.messages=messages
        return SimpleNamespace(content=self.content,response_metadata={'done_reason':self.reason},usage_metadata={'output_tokens':20})


def agent(tmp_path,model):
    result=OllamaAgents.__new__(OllamaAgents);result.model=model;result.model_name='test'
    result.trace_directory=tmp_path/'calls';result.invocation_context={'task_id':'task','parent_task_id':'parent','actor':'frontend'}
    return result


def test_raw_source_is_traced_and_keeps_real_call_identity(tmp_path):
    model=Model('```tsx\nexport const value="quoted";\n```');worker=agent(tmp_path,model);events=[]
    worker.activity=lambda status,payload:events.append((status,payload))
    assert worker.generate_source('Implement this file',{'write_target':'app/page.tsx'})=='export const value="quoted";\n'
    trace=json.loads(next(worker.trace_directory.glob('*.json')).read_text())
    assert trace['response_format']=='raw_source' and trace['task_id']=='task' and trace['done_reason']=='stop'
    assert trace['requested_options']['num_predict']==6000 and trace['requested_options']['num_ctx']==32768
    assert trace['output']==model.content and trace['call_id']==worker.last_call_identity['call_id']
    assert [event for event,_ in events]==['AGENT_CALL_STARTED','AGENT_CALL_COMPLETED']
    assert all('output' not in payload for _,payload in events)


@pytest.mark.parametrize('reason',['length',None])
def test_provider_truncation_cannot_be_accepted_as_source(tmp_path,reason):
    worker=agent(tmp_path,Model('export const partial=',reason))
    with pytest.raises(ProviderResourceError,match='did not complete'):worker.generate_source('Implement',{})
    trace=json.loads(next(worker.trace_directory.glob('*.json')).read_text())
    assert trace['outcome']=='ERROR' and 'did not complete' in trace['validation_error']
