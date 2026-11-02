import json

import pytest

from forge.source_agent import SourceAgent,build_evidence,diagnostic_context,REPAIR_INSTRUCTION
from forge.tasks import CheckEvidence,Observation,TaskConflict
from forge.workspace import source_fingerprint
from forge.workspace_tools import file_hash
from test_workspace_tools import tools


class Agent:
    model_name='test'
    activity=None
    def __init__(self,content):self.content=content;self.data=None
    def generate(self,schema,instruction,data,**_):
        self.data=data;self.instruction=instruction;self.last_call_identity={'call_id':'model-call'}
        if schema.__name__=='RepairFocus':
            return schema.model_validate({'file':data['allowed_targets'][0],'cause':'Observed compiler failure',
                'changes':['Correct the reported source expression while preserving behavior']})
        path=data['allowed_targets'][0]
        old=data['source'].get(path)
        if data['repair_mode'] and old:
            return schema.model_validate({'tool':'replace_text','path':path,
                'edits':[{'old':old['content'],'new':self.content}],
                'expected_sha256':old['sha256'],'expected_workspace_fingerprint':data['workspace_fingerprint']})
        return schema.model_validate({'tool':'write_file','path':path,'content':self.content,
            'expected_sha256':old['sha256'] if old else None,'expected_workspace_fingerprint':data['workspace_fingerprint'],
            'require_change':data['repair_mode']})


def configured(tools,mode=None):
    inputs={'original_request':'Build an interactive page with a visible result.','file':'app/page.tsx'}
    if mode:inputs['mode']=mode
    state=tools.ledger.revise(tools.state,tools.state.task.model_copy(update={'inputs':inputs,
        'required_checks':['isolated_build' if mode else 'source_written']}))
    state=tools.ledger.reserve_action(tools.ledger.start(state),'frontend')
    if mode:
        fp=source_fingerprint(tools.root)
        state=tools.ledger.observe(state,Observation(revision=state.revision,fingerprint=fp,
            checks=[CheckEvidence(check='isolated_build',exit_code=1,fingerprint=fp,report='failed-build.json',
                summary='app/page.tsx(1,1): error TS1234: actual compiler evidence')]))
        state=tools.ledger.reserve_action(state,'frontend')
    return state


def test_model_proposes_actual_owned_write_with_original_goal_and_live_source(tools):
    state=configured(tools)
    agent=Agent('export default function Page(){return <main>Model source</main>}')
    worker=SourceAgent(tools.ledger,agent,tools.root,tools.draft,workspace_boundary=tools.root.parent)
    checks=worker(state)
    assert checks[0].check=='source_written' and checks[0].exit_code==0
    assert checks[0].fingerprint==file_hash(tools.root/'app/page.tsx')
    assert agent.data['original_request']==state.task.inputs['original_request']
    assert 'tsconfig.json' in agent.data['source'] and 'schema' not in agent.data['capabilities']
    packet=json.loads(__import__('pathlib').Path(checks[0].report).read_text())
    assert packet['initiator']=='model' and packet['proposal_call_id']=='model-call'
    assert tools.ledger.read(state.task.id).status=='running'


def test_missing_original_context_prevents_ungrounded_generation(tools):
    agent=Agent('unused')
    with pytest.raises(ValueError,match='original user request'):
        SourceAgent(tools.ledger,agent,tools.root,tools.draft,workspace_boundary=tools.root.parent)(tools.state)
    assert agent.data is None


def test_other_files_changing_during_model_call_cannot_accept_stale_edit(tools):
    state=configured(tools)
    class RacingAgent(Agent):
        def generate(self,*args,**kwargs):
            proposal=super().generate(*args,**kwargs)
            (tools.root/'app/globals.css').write_text('changed while model was generating',encoding='utf-8')
            return proposal
    with pytest.raises(ValueError,match='context changed'):
        SourceAgent(tools.ledger,RacingAgent('export default function Page(){return null}'),tools.root,tools.draft,workspace_boundary=tools.root.parent)(state)
    assert not (tools.root/'app/page.tsx').exists()


def test_cleanup_or_environment_failure_cannot_be_accepted_as_successful_build(tools):
    tools.check_runner=lambda root,*_: {'passed':False,'report':'actual-check.json',
        'source_fingerprint':source_fingerprint(root),'coverage':{'application_behavior':'NOT_TESTED'},
        'checks':{'results':[{'name':'typecheck','exit_code':0,'stopped':None,'output':''},
                             {'name':'production_build','exit_code':0,'stopped':None,'output':''}]},
        'error':'cleanup failed'}
    checks=build_evidence(tools)
    assert checks[0].check=='isolated_build' and checks[0].exit_code==1


def test_repair_worker_uses_actual_failures_and_returns_fresh_build_evidence(tools):
    state=configured(tools,'repair_build');agent=Agent('export default function Page(){return <main>Fixed</main>}')
    def check(root,*_):return {'passed':True,'report':'fresh.json','source_fingerprint':source_fingerprint(root),
        'coverage':{'application_behavior':'NOT_TESTED'},'checks':{'results':[{'name':'production_build','exit_code':0,'output':'built','stopped':None}]}}
    worker=SourceAgent(tools.ledger,agent,tools.root,tools.draft,workspace_boundary=tools.root.parent,check_runner=check)
    result=worker(state)
    assert result[0].check=='isolated_build' and result[0].exit_code==0
    assert result[0].fingerprint==source_fingerprint(tools.root)
    assert agent.data['repair_focus']['file']=='app/page.tsx'
    assert agent.instruction==REPAIR_INSTRUCTION
    assert agent.data['acceptance_criteria']==tools.draft.acceptance_criteria
    assert 'app_design' not in agent.data
    assert 'tsconfig.json' in agent.data['source']
    assert any(t.task.owner=='qa' and t.task.parent_id==state.task.id for t in tools.ledger.list())


def test_latest_build_failure_survives_unproductive_intermediate_attempts(tools):
    state=configured(tools,'repair_build')
    for message in ['Rejected source proposal','Unchanged edit']:
        state=tools.ledger.observe(state,Observation(revision=state.revision,fingerprint=source_fingerprint(tools.root),error=message))
    state=tools.ledger.reserve_action(state,'frontend')
    agent=Agent('export default function Page(){return <main>Fixed</main>}')
    def check(root,*_):return {'passed':False,'report':'build.json','source_fingerprint':source_fingerprint(root),
        'coverage':{'application_behavior':'NOT_TESTED'},'checks':{'results':[]},'error':'still failing'}
    SourceAgent(tools.ledger,agent,tools.root,tools.draft,workspace_boundary=tools.root.parent,check_runner=check)(state)
    assert agent.data['latest_build_failure']['checks'][0]['report']=='failed-build.json'
    assert agent.data['last_tool_error']=='Unchanged edit'
    assert 'recent_failures' not in agent.data and 'recovery_strategy' not in agent.data


def test_diagnostic_context_points_to_the_exact_expression_not_a_guessed_callee():
    line='const result = returnsVoid() && next();'
    source={'lib/compute.ts':{'content':'// module\n'+line+'\n'}}
    failure={'checks':[{'summary':"typecheck: lib/compute.ts(2,16): error TS1345: A void expression cannot be tested."}]}
    context=diagnostic_context(failure,source)
    assert context[0]['expression_at_column'].startswith('returnsVoid()')
    assert context[0]['line_text']==line and context[0]['column']==16


def test_existing_source_repairs_use_a_model_proposed_patch(tools):
    (tools.root/'app/page.tsx').write_text('export default function Page(){return null}',encoding='utf-8')
    state=configured(tools,'repair_build');agent=Agent('export default function Page(){return <main>Updated</main>}')
    def check(root,*_):return {'passed':True,'report':'check.json','source_fingerprint':source_fingerprint(root),
        'coverage':{'application_behavior':'NOT_TESTED'},'checks':{'results':[]}}
    SourceAgent(tools.ledger,agent,tools.root,tools.draft,workspace_boundary=tools.root.parent,check_runner=check)(state)
    events=tools.ledger.store.read(tools.ledger.job_id)['events']
    patch=next(event for event in events if event['status']=='TOOL_CALL_COMPLETED' and event['payload']['tool']=='replace_text')
    assert patch['payload']['initiator']=='model' and patch['payload']['proposal_call_id']=='model-call'


@pytest.mark.parametrize('patch_rejected',[False,True])
def test_repair_can_replace_a_complete_file_without_bypassing_change_guards(tools,patch_rejected):
    path=tools.root/'app/page.tsx'
    path.write_text('export default function Page(){return null}',encoding='utf-8')
    state=configured(tools,'repair_build')
    if patch_rejected:
        state=tools.ledger.observe(state,Observation(revision=state.revision,
            fingerprint=source_fingerprint(tools.root),error='ValueError: Patch snippet must match exactly once; found 2 matches.'))
        state=tools.ledger.reserve_action(state,'frontend')
    class RewriteAgent(Agent):
        def generate(self,schema,instruction,data,**kwargs):
            if schema.__name__=='RepairFocus':return super().generate(schema,instruction,data,**kwargs)
            target=data['allowed_targets'][0]
            if patch_rejected:
                assert data['replace_rejected_patch'] and 'complete corrected file' in data['edit_guidance']
                from pydantic import ValidationError
                with pytest.raises(ValidationError):
                    schema.model_validate({'tool':'replace_text','path':target,
                        'edits':[{'old':'return null','new':'return 1'}],
                        'expected_sha256':data['source'][target]['sha256'],
                        'expected_workspace_fingerprint':data['workspace_fingerprint']})
            return schema.model_validate({'tool':'write_file','path':target,'content':self.content,
                'expected_sha256':data['source'][target]['sha256'],
                'expected_workspace_fingerprint':data['workspace_fingerprint'],'require_change':True})
    def check(root,*_):return {'passed':False,'report':'check.json','source_fingerprint':source_fingerprint(root),
        'coverage':{'application_behavior':'NOT_TESTED'},'checks':{'results':[]},'error':'fixture check'}
    content='export default function Page(){return <main>Corrected</main>}'
    worker=SourceAgent(tools.ledger,RewriteAgent(content),tools.root,tools.draft,
        workspace_boundary=tools.root.parent,check_runner=check)
    worker(state)
    assert path.read_text()==content
    with pytest.raises(ValueError,match='unchanged source'):worker(state)


def test_fresh_build_evidence_clears_older_tool_rejection(tools):
    state=configured(tools,'repair_build')
    state=tools.ledger.observe(state,Observation(revision=state.revision,
        fingerprint=source_fingerprint(tools.root),error='Patch snippet must match exactly once'))
    state=tools.ledger.observe(state,state.observations[0])
    state=tools.ledger.reserve_action(state,'frontend')
    agent=Agent('export default function Page(){return <main>Fixed</main>}')
    def check(root,*_):return {'passed':False,'report':'check.json','source_fingerprint':source_fingerprint(root),
        'coverage':{'application_behavior':'NOT_TESTED'},'checks':{'results':[]},'error':'fixture check'}
    SourceAgent(tools.ledger,agent,tools.root,tools.draft,workspace_boundary=tools.root.parent,check_runner=check)(state)
    assert agent.data['last_tool_error']=='' and not agent.data['replace_rejected_patch']
