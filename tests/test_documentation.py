import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import RootModel

from forge import documentation as docs
from forge.agents import OllamaAgents
from forge.handoffs import record_handoff
from forge.persistence import JobStore
from forge.tasks import Envelope,Task,TaskLedger,TaskConflict,TaskBlockedError
from test_workspace_tools import tools


TEXT='Browser localStorage stores data across browser sessions. Read and write it in client-side code, not while rendering on the server. '


def page(url,text=TEXT):
    digest=hashlib.sha256(text.encode()).hexdigest()
    return {'url':url,'text':text,'content_sha256':digest,'text_sha256':digest,'retrieved_at':'2026-11-05T00:00:00+00:00'}


def test_lookup_selects_official_sources_and_reuses_intact_cache(tmp_path):
    calls=[]
    def fetch(url):calls.append(url);return page(url)
    request={'tool':'lookup_documentation','query':'localStorage persistence browser sessions'}
    first=docs.lookup(request,tmp_path,fetcher=fetch)
    assert first['status']=='ok' and first['discovery']=='official_documentation_index'
    assert first['sources'][0]['url'].startswith('https://developer.mozilla.org/')
    assert 'across browser sessions' in first['sources'][0]['excerpt']
    count=len(calls)
    assert all(item['cached'] for item in docs.lookup(request,tmp_path,fetcher=fetch)['sources'])
    assert len(calls)==count
    cache=next((tmp_path/'cache').glob('*.json'));packet=json.loads(cache.read_text())
    packet['page']['text']='Altered cached facts';cache.write_text(json.dumps(packet))
    docs.lookup(request,tmp_path,fetcher=fetch)
    assert len(calls)==count+1


@pytest.mark.parametrize('url',['http://nextjs.org/docs','https://127.0.0.1/admin',
    'https://[::1]/','https://localhost/','https://nextjs.org.attacker.example/',
    'https://user:password@nextjs.org/docs','https://nextjs.org:8787/docs',
    'file:///etc/passwd','https://nextjs.org/docs?secret=private'])
def test_invalid_urls_never_reach_network(tmp_path,url):
    def forbidden(_):raise AssertionError('Unsafe request reached network')
    result=docs.lookup({'tool':'lookup_documentation','query':'API question','urls':[url]},tmp_path,fetcher=forbidden)
    assert result['status']=='unavailable' and result['sources'][0]['status']=='rejected'


def test_redirects_are_checked_before_following():
    with pytest.raises(ValueError):docs._Redirects().redirect_request(None,None,302,'redirect',{},'http://127.0.0.1/private')


def test_official_page_anchors_do_not_block_retrieval():
    assert docs.allowed_url('https://react.dev/reference/react/useEffect#usage')=='https://react.dev/reference/react/useEffect'


def test_outages_are_reference_failures_not_api_absence(tmp_path):
    def offline(_):raise TimeoutError('Offline')
    result=docs.lookup({'tool':'lookup_documentation','query':'browser storage'},tmp_path,fetcher=offline)
    assert result['status']=='unavailable'
    assert all('excerpt' not in item for item in result['sources'])


def test_html_parser_ignores_executable_and_navigation_content():
    parser=docs._Text();parser.feed('<nav>Navigation</nav><script>run_code()</script><main><h1>API</h1><p>Storage persists.</p></main>')
    text=''.join(parser.parts)
    assert 'Storage persists' in text and 'run_code' not in text and 'Navigation' not in text


class Answer(Envelope):
    value: int


class SequenceModel:
    def __init__(self,values,*,raw=False):self.values=iter(values);self.calls=[];self.raw=raw
    def model_copy(self,*,update):return self
    def with_structured_output(self,schema,**kwargs):self.schema=schema;return self
    def invoke(self,messages):
        self.calls.append(messages);value=next(self.values)
        content=value if isinstance(value,str) else json.dumps(value)
        raw=SimpleNamespace(content=content,response_metadata={'done_reason':'stop'},usage_metadata={})
        return raw if self.raw else {'raw':raw,'parsed':self.schema.model_validate(value),'parsing_error':None}


def agent(tmp_path,values,*,raw=False):
    store=JobStore(tmp_path/'jobs.sqlite3');job=store.create()
    ledger=TaskLedger(store,job)
    state=ledger.reserve_action(ledger.start(ledger.create(Task(owner='frontend',goal='Implement independently',required_checks=['source_written']))),'frontend')
    result=OllamaAgents.__new__(OllamaAgents);result.model_name='qwen2.5-coder:7b'
    result.model=SequenceModel(values,raw=raw);result.trace_directory=tmp_path/'model-calls'/job
    result.documentation_fetcher=page
    record_handoff(store,job,'coordinator','frontend','Implement from the request.',{},agents=result,task_id=state.task.id,task_state=state)
    return result,ledger,state


REQUEST={'tool':'lookup_documentation','query':'browser localStorage persistence'}


def test_structured_agent_requests_docs_and_returns_original_answer_schema(tmp_path):
    worker,ledger,state=agent(tmp_path,[REQUEST,{'value':7}])
    answer=worker.generate(Answer,'Choose the correct value.',{'original_request':'Business requirements only'},coding=True)
    assert type(answer) is Answer and answer.value==7
    assert len(worker.model.calls)==2
    context=json.loads(worker.model.calls[-1][-1][1])
    assert context['original_request']=='Business requirements only'
    assert context['documentation_evidence'][0]['sources'][0]['content_sha256']
    trace=json.loads(Path(worker.last_call_identity['report']).read_text())
    handoff=next(event for event in ledger.store.read(ledger.job_id)['events']
        if event['status']=='AGENT_HANDOFF' and event['payload']['handoff_id']==trace['handoff_id'])
    saved=json.loads(Path(handoff['payload']['report']).read_text())
    assert saved['context']==context and saved['sender']=='documentation'
    events=ledger.store.read(ledger.job_id)['events']
    assert any(event['status']=='DOCUMENTATION_LOOKUP_COMPLETED' for event in events)
    assert ledger.read(state.task.id).status=='running'  # Looking up a reference never completes source work.


def test_nested_root_answer_keeps_its_public_protocol(tmp_path):
    class RootAnswer(RootModel[Answer]):pass
    worker,_,_=agent(tmp_path,[REQUEST,{'value':9}])
    assert worker.generate(RootAnswer,'Answer',{}).root.value==9


def test_raw_source_tool_request_never_becomes_source(tmp_path):
    worker,_,_=agent(tmp_path,[json.dumps(REQUEST),'export const value=7;'],raw=True)
    source=worker.generate_source('Implement the owned file.',{'write_target':'app/page.tsx'})
    assert source=='export const value=7;\n' and 'lookup_documentation' not in source
    assert len(worker.model.calls)==2
    assert 'documentation_evidence' in json.loads(worker.model.calls[-1][-1][1])


def test_lookup_loop_is_bounded_and_does_not_relabel_uncertainty_as_app_failure(tmp_path):
    worker,ledger,state=agent(tmp_path,[REQUEST,REQUEST,REQUEST])
    with pytest.raises(TaskBlockedError,match='lookup budget'):worker.generate(Answer,'Answer',{})
    assert len(worker.model.calls)==3
    assert sum(event['status']=='DOCUMENTATION_LOOKUP_STARTED' for event in ledger.store.read(ledger.job_id)['events'])==2
    assert not ledger.read(state.task.id).observations


def test_stale_handoff_cannot_fetch_or_ask_for_another_answer(tmp_path):
    worker,ledger,state=agent(tmp_path,[REQUEST,{'value':7}])
    def revise(url):
        ledger.revise(ledger.read(state.task.id),state.task)
        return page(url)
    worker.documentation_fetcher=revise
    with pytest.raises(TaskConflict):worker.generate(Answer,'Answer',{})
    assert len(worker.model.calls)==1


def test_observed_build_failure_triggers_research_before_overconfident_answer(tmp_path):
    worker,_,_=agent(tmp_path,[{'value':7}])
    result=worker.generate(Answer,'Answer',{'latest_build_failure':{'summary':'TypeScript TS2307 module import does not resolve'}})
    assert result.value==7 and len(worker.model.calls)==1
    data=json.loads(worker.model.calls[0][-1][1])
    assert data['documentation_evidence'][0]['status']=='ok'


def test_diagnostic_metadata_cannot_hide_the_actual_lookup_question(tmp_path):
    worker,_,_=agent(tmp_path,[{'value':7}])
    worker.generate(Answer,'Answer',{'latest_build_failure':{'fingerprint':'a'*64,'report':'a'*500,
        'checks':[{'summary':'TypeScript TS2307 module import does not resolve'}]}})
    data=json.loads(worker.model.calls[0][-1][1])
    assert data['documentation_evidence'][0]['query']=='TypeScript TS2307 module import does not resolve'


def test_builder_reads_docs_before_writing_and_retains_syntax_gate(tools):
    from forge.source_agent import SourceAgent
    from test_source_agent import configured
    state=configured(tools)
    worker=OllamaAgents.__new__(OllamaAgents);worker.model_name='qwen2.5-coder:7b'
    worker.model=SequenceModel([json.dumps(REQUEST),'export default function Page(){return <main>Saved notes</main>}'],raw=True)
    def fetch(url):
        assert not (tools.root/'app/page.tsx').exists()
        return page(url)
    worker.documentation_fetcher=fetch
    checks=SourceAgent(tools.ledger,worker,tools.root,tools.draft,workspace_boundary=tools.root.parent)(state)
    assert all(check.exit_code==0 for check in checks)
    assert checks[-1].check=='source_syntax'
    assert 'lookup_documentation' not in (tools.root/'app/page.tsx').read_text()
    written=json.loads(Path(checks[0].report).read_text())
    assert written['proposal_call_id']==worker.last_call_identity['call_id']
