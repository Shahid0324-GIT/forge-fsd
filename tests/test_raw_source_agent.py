import json
from pathlib import Path

import pytest

from forge.source_agent import SourceAgent
from forge.tasks import TaskConflict
from forge.tasks import Observation,CheckEvidence
from forge.workspace import source_fingerprint
from test_source_agent import Agent,configured
from test_workspace_tools import tools


class RawAgent(Agent):
    def __init__(self,content,target=None):super().__init__(content);self.target=target;self.raw_calls=[]
    def generate(self,schema,instruction,data,**kwargs):
        if schema.__name__=='SourceTarget':return schema.model_validate({'path':self.target or data['allowed_targets'][0],'change':'Correct the observed failure'})
        assert schema.__name__!='SourceEdit','Raw source must not be generated as a JSON tool body'
        return super().generate(schema,instruction,data,**kwargs)
    def generate_source(self,instruction,data):
        self.raw_calls.append(data);self.last_call_identity={'call_id':'raw-source-call'};return self.content


def good_check(root,*_):
    from forge.workspace import source_fingerprint
    return {'passed':True,'report':'check.json','source_fingerprint':source_fingerprint(root),
        'coverage':{'application_behavior':'NOT_TESTED'},'checks':{'results':[]}}


def cycle_state(tools):
    (tools.root/'app/page.tsx').write_text("import {useState} from 'react';\nexport default function Page(){return null}\n")
    state=configured(tools,'repair_build');current=source_fingerprint(tools.root);old='a'*64
    for fp,summary,error in [
        (old,"app/page.tsx(1,1): error TS2307: Cannot find module './helper'.",''),
        (current,'app/page.tsx(1,1): CLIENT_HOOK_WITHOUT_DIRECTIVE: Missing client boundary',''),
        (current,'',f'Repair cycle rejected: this would restore an already failed workspace {old}.')]:
        state=tools.ledger.observe(state,Observation(revision=state.revision,fingerprint=fp,error=error,
            checks=[] if not summary else [CheckEvidence(check='isolated_build',exit_code=1,fingerprint=fp,report='missing.json',summary=summary)]))
        state=tools.ledger.reserve_action(state,'frontend')
    return state


def test_cycle_body_receives_separate_actions_for_current_and_rejected_failures(tools):
    state=cycle_state(tools)
    class CycleAgent(RawAgent):
        def generate(self,schema,instruction,data,**kwargs):
            if schema.__name__=='CycleRepairActions':
                self.obligations=data['failure_obligations']
                return schema.model_validate({key:'Correct this reported cause using actual module boundaries' for key in schema.model_fields})
            return super().generate(schema,instruction,data,**kwargs)
    agent=CycleAgent("'use client';\nexport default function Page(){return <main>Result</main>}\n")
    SourceAgent(tools.ledger,agent,tools.root,tools.draft,workspace_boundary=tools.root.parent,check_runner=good_check)(state)
    context=agent.raw_calls[0]
    assert len(context['cycle_repair_actions'])==2
    assert {row['source_state'] for row in agent.obligations}=={'current','rejected_candidate'}
    assert 'repair_focus' not in context and 'selected_change' not in context


def test_incomplete_cycle_plan_cannot_reach_source_generation(tools):
    state=cycle_state(tools)
    class Incomplete(RawAgent):
        def generate(self,schema,*args,**kwargs):
            if schema.__name__=='CycleRepairActions':return {next(iter(schema.model_fields)):'Only one cause'}
            return super().generate(schema,*args,**kwargs)
    agent=Incomplete('Must not write');before=(tools.root/'app/page.tsx').read_text()
    with pytest.raises(ValueError):
        SourceAgent(tools.ledger,agent,tools.root,tools.draft,workspace_boundary=tools.root.parent,check_runner=good_check)(state)
    assert not agent.raw_calls and (tools.root/'app/page.tsx').read_text()==before


@pytest.mark.parametrize('race',['source','revision'])
def test_cycle_planning_revalidates_snapshot_and_task_before_body(tools,race):
    state=cycle_state(tools)
    class RacingCycle(RawAgent):
        def generate(self,schema,*args,**kwargs):
            if schema.__name__=='CycleRepairActions':
                actions=schema.model_validate({key:'Correct reported cause' for key in schema.model_fields})
                if race=='source':(tools.root/'app/globals.css').write_text('/* changed during cycle planning */')
                else:tools.ledger.revise(state,state.task)
                return actions
            return super().generate(schema,*args,**kwargs)
    agent=RacingCycle('Must not write');before=(tools.root/'app/page.tsx').read_text()
    with pytest.raises((ValueError,TaskConflict)):
        SourceAgent(tools.ledger,agent,tools.root,tools.draft,workspace_boundary=tools.root.parent,check_runner=good_check)(state)
    assert not agent.raw_calls and (tools.root/'app/page.tsx').read_text()==before


def test_raw_source_uses_scoped_writer_and_records_body_call_identity(tools):
    state=configured(tools);source='export default function Page(){return <main title="Café">Hello</main>}\n'
    agent=RawAgent(source)
    checks=SourceAgent(tools.ledger,agent,tools.root,tools.draft,workspace_boundary=tools.root.parent)(state)
    assert (tools.root/'app/page.tsx').read_text(encoding='utf-8')==source
    assert agent.raw_calls[0]['write_target']=='app/page.tsx'
    report=json.loads(Path(checks[0].report).read_text())
    assert report['initiator']=='model' and report['proposal_call_id']=='raw-source-call'


def test_raw_repair_can_choose_another_owned_file_without_following_wrong_qa_target(tools):
    state=configured(tools,'repair_build')
    draft=tools.draft.model_copy(update={'files':[*tools.draft.files,
        tools.draft.files[0].model_copy(update={'path':'app/layout.tsx','purpose':'Server layout'})]})
    agent=RawAgent('export const metadata={title:"Preserved"};','app/layout.tsx')
    SourceAgent(tools.ledger,agent,tools.root,draft,workspace_boundary=tools.root.parent,check_runner=good_check)(state)
    assert (tools.root/'app/layout.tsx').read_text()==agent.content
    assert agent.raw_calls[0]['repair_focus']['file']=='app/page.tsx'
    assert agent.raw_calls[0]['write_target']=='app/layout.tsx'


def test_raw_target_selection_cannot_choose_another_owners_file(tools):
    state=configured(tools,'repair_build');agent=RawAgent('Must not be written','lib/types.ts')
    draft=tools.draft.model_copy(update={'files':[*tools.draft.files,
        tools.draft.files[0].model_copy(update={'path':'app/layout.tsx','purpose':'Server layout'})]})
    with pytest.raises(ValueError):
        SourceAgent(tools.ledger,agent,tools.root,draft,workspace_boundary=tools.root.parent,check_runner=good_check)(state)
    assert not agent.raw_calls and not (tools.root/'lib/types.ts').exists()


@pytest.mark.parametrize('during',['selection','body','revision'])
def test_expired_context_in_raw_generation_cannot_write(tools,during):
    state=configured(tools,'repair_build' if during=='selection' else None)
    draft=tools.draft.model_copy(update={'files':[*tools.draft.files,
        tools.draft.files[0].model_copy(update={'path':'app/layout.tsx','purpose':'Server layout'})]})
    class Racing(RawAgent):
        def generate(self,schema,*args,**kwargs):
            selected=super().generate(schema,*args,**kwargs)
            if during=='selection' and schema.__name__=='SourceTarget':(tools.root/'app/globals.css').write_text('changed')
            return selected
        def generate_source(self,*args,**kwargs):
            content=super().generate_source(*args,**kwargs)
            if during=='body':(tools.root/'app/globals.css').write_text('changed')
            if during=='revision':tools.ledger.revise(state,state.task)
            return content
    agent=Racing('export default function Page(){return null}')
    with pytest.raises((ValueError,TaskConflict)):
        SourceAgent(tools.ledger,agent,tools.root,draft,workspace_boundary=tools.root.parent,check_runner=good_check)(state)
    assert not (tools.root/'app/page.tsx').exists()
    if during=='selection':assert not agent.raw_calls
