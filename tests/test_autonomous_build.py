import json
from pathlib import Path

import pytest

from forge.autonomous_build import build_app,build_resumable
from forge.autonomous_planning import plan_app
from forge.autonomous_review import decide_plan,review_snapshot,request_changes
from forge.persistence import JobStore
from forge.tasks import TaskLedger
from forge.workspace import source_fingerprint
from test_autonomous_planning import Agent,draft


class Builder(Agent):
    def __init__(self,proposal):
        super().__init__(proposal);self.edits=[];self.cancel=None;self.review_contexts=[]
    def generate(self,schema,instruction,data,**kwargs):
        if schema.__name__=='RepairFocus':
            return schema.model_validate({'file':data['allowed_targets'][0],'cause':'Actual compiler failure','changes':['Correct the reported expression']})
        if schema.__name__=='RecoveryDecision':
            self.review_contexts.append(data['app_context'])
            return schema.model_validate({'diagnosis':'Previous edit did not improve the check','strategy':'Inspect the concrete diagnostic before editing',
                'action':'retry','owner':data['current_owner'],'question':''})
        if schema.__name__!='SourceEdit':return super().generate(schema,instruction,data,**kwargs)
        path=data['allowed_targets'][0];self.edits.append(path)
        if self.cancel:self.cancel()
        content='export function sum(a:number,b:number){return a+b}' if path.startswith('lib/') else 'import {sum} from "../lib/math"; export default function Page(){return <main>{sum(1,2)}</main>}'
        return schema.model_validate({'tool':'write_file','path':path,'content':content,
            'expected_sha256':data['source'].get(path,{}).get('sha256'),
            'expected_workspace_fingerprint':data['workspace_fingerprint'],'require_change':data['repair_mode']})


@pytest.fixture
def setup(tmp_path):
    proposal=draft();proposal=type(proposal).model_validate({**proposal.model_dump(),'files':[
        {'path':'lib/math.ts','owner':'backend','purpose':'Shared calculation'},
        {'path':'app/page.tsx','owner':'frontend','purpose':'Show the calculated value'}],
        'interfaces':[{'name':'calculation','provider':'lib/math.ts','consumers':['app/page.tsx'],
            'kind':'module','contract':'export function sum(a:number,b:number):number'}]})
    agent=Builder(proposal);store=JobStore(tmp_path/'artifacts/jobs.sqlite3')
    record=plan_app('Build a page showing the calculated value.',agent,store)
    job=record['job_id'];review=review_snapshot(job,store)
    return store,job,agent,tmp_path/'workspace',review


def runner(passed=True):
    def check(root,directory,job):
        directory.mkdir(parents=True,exist_ok=True);path=directory/'fixture-check.json'
        result={'passed':passed,'report':str(path),'source_fingerprint':source_fingerprint(root),
            'coverage':{'application_behavior':'NOT_TESTED'},'checks':{'results':[
                {'name':'typecheck','exit_code':0 if passed else 2,'stopped':None,'output':'' if passed else 'app/page.tsx(1,1): error TS1234: Controlled failure'},
                {'name':'production_build','exit_code':0,'stopped':None,'output':'fixture build'}]}}
        path.write_text(json.dumps(result),encoding='utf-8');return result
    return check


def approve(store,job,review):decide_plan(job,store,review['fingerprint'],approved=True,actor='test_operator')


def test_invalid_provider_is_corrected_before_consumer_is_delegated(setup):
    store,job,agent,boundary,review=setup;approve(store,job,review)
    original=agent.generate;attempts=[]
    def generate(schema,instruction,data,**kwargs):
        if schema.__name__=='SourceEdit' and data['allowed_targets']==['lib/math.ts']:
            attempts.append(data)
            if len(attempts)==1:
                proposal=original(schema,instruction,data,**kwargs)
                return schema.model_validate({**proposal.root.model_dump(),'content':'export function sum(a: = 1'})
            assert data['recent_failures'][-1]['checks'][-1]['check']=='source_syntax'
            assert data['recent_failures'][-1]['checks'][-1]['exit_code']==1
            assert 'error TS' in data['recent_failures'][-1]['checks'][-1]['summary']
            assert data['source']['lib/math.ts']['content']=='export function sum(a: = 1'
            assert not (boundary/job/'app/page.tsx').exists()
        return original(schema,instruction,data,**kwargs)
    agent.generate=generate
    result=build_app(job,agent,store,workspace_boundary=boundary,check_runner=runner())
    assert result['status']=='AUTONOMOUS_BUILD_CHECKS_PASSED'
    assert agent.edits==['lib/math.ts','lib/math.ts','app/page.tsx']
    provider=next(task for task in TaskLedger(store,job).list() if task.task.inputs.get('file')=='lib/math.ts')
    assert len(provider.observations)==2 and provider.observations[-1].checks[-1].exit_code==0


def test_source_generation_requires_approval_before_creating_a_workspace(setup):
    store,job,agent,boundary,_=setup
    with pytest.raises(ValueError,match='requires an approved'):build_app(job,agent,store,workspace_boundary=boundary,check_runner=runner())
    assert not boundary.exists() and not agent.edits


def test_approved_manifest_drives_multi_role_generation_without_readiness_promotion(setup):
    store,job,agent,boundary,review=setup;approve(store,job,review)
    result=build_app(job,agent,store,workspace_boundary=boundary,check_runner=runner())
    assert result['status']=='AUTONOMOUS_BUILD_CHECKS_PASSED'
    assert agent.edits==['lib/math.ts','app/page.tsx']
    assert result['events'][-1]['payload']['application_behavior']=='NOT_TESTED'
    assert not any(e['status'] in {'FUNCTIONALLY_VERIFIED','READY','PREVIEW_RUNNING'} for e in result['events'])
    assert result['events'][-1]['payload']['source_fingerprint']==source_fingerprint(boundary/job)
    assert all(state.status=='completed' for state in TaskLedger(store,job).list())


def test_missing_verification_environment_pauses_before_any_source_repair_or_senior_review(setup):
    store,job,agent,boundary,review=setup;approve(store,job,review)
    def missing(root,directory,job):
        result=runner(False)(root,directory,job)
        result.update(error='Dependency image unavailable',environment_failure={'stage':'image_inspection'},checks={'results':[]})
        return result
    result=build_app(job,agent,store,workspace_boundary=boundary,check_runner=missing)
    assert result['status']=='AUTONOMOUS_BUILD_PAUSED'
    assert agent.edits==['lib/math.ts','app/page.tsx'] and not agent.review_contexts
    state=TaskLedger(store,job).read(result['events'][-1]['payload']['task_id'])
    assert state.actions_used==1 and not state.observations
    assert 'restore the execution environment' in state.pause_reason


def test_resume_checks_current_source_without_regenerating_completed_files(setup):
    store,job,agent,boundary,review=setup;approve(store,job,review)
    paused=build_app(job,agent,store,workspace_boundary=boundary,check_runner=runner(False))
    assert paused['status']=='AUTONOMOUS_BUILD_PAUSED' and build_resumable(paused,store,workspace_boundary=boundary)
    edits=list(agent.edits);fingerprint=source_fingerprint(boundary/job)
    result=build_app(job,agent,store,resume=True,additional_actions=3,workspace_boundary=boundary,check_runner=runner())
    assert result['status']=='AUTONOMOUS_BUILD_CHECKS_PASSED'
    assert agent.edits==edits and source_fingerprint(boundary/job)==fingerprint


def test_cancellation_during_model_call_prevents_source_write(setup):
    store,job,agent,boundary,review=setup;approve(store,job,review)
    agent.cancel=lambda:store.event(job,'CANCELLED',{'actor':'test_operator'})
    with pytest.raises(ValueError,match='not authorized'):
        build_app(job,agent,store,workspace_boundary=boundary,check_runner=runner())
    assert store.read(job)['status']=='CANCELLED' and not (boundary/job/'lib/math.ts').exists()


def test_existing_workspace_is_not_overwritten_and_model_selection_is_bound(setup):
    store,job,agent,boundary,review=setup;approve(store,job,review)
    agent.model_name='qwen2.5-coder:3b'
    with pytest.raises(ValueError,match='approved job model'):build_app(job,agent,store,workspace_boundary=boundary,check_runner=runner())
    agent.model_name='qwen2.5-coder:7b';(boundary/job).mkdir(parents=True)
    marker=boundary/job/'keep.txt';marker.write_text('existing source')
    with pytest.raises(ValueError,match='untracked workspace'):build_app(job,agent,store,workspace_boundary=boundary,check_runner=runner())
    assert marker.read_text()=='existing source' and not agent.edits


def test_resume_cannot_adopt_modified_runtime_configuration(setup):
    store,job,agent,boundary,review=setup;approve(store,job,review)
    build_app(job,agent,store,workspace_boundary=boundary,check_runner=runner(False))
    (boundary/job/'package.json').write_text('{}',encoding='utf-8');before=list(agent.edits)
    assert not build_resumable(store.read(job),store,workspace_boundary=boundary)
    with pytest.raises(ValueError,match='runtime configuration'):
        build_app(job,agent,store,resume=True,workspace_boundary=boundary,check_runner=runner())
    assert agent.edits==before and store.read(job)['status']=='AUTONOMOUS_BUILD_PAUSED'


def test_senior_build_review_retains_human_feedback_and_original_goal(setup):
    store,job,agent,boundary,review=setup
    request_changes(job,agent,store,review['fingerprint'],'Keep the calculation visible on the page.',actor='test_operator')
    review=review_snapshot(job,store);approve(store,job,review)
    result=build_app(job,agent,store,workspace_boundary=boundary,check_runner=runner(False))
    assert result['status']=='AUTONOMOUS_BUILD_PAUSED' and agent.review_contexts
    assert all(context['human_review_feedback']==['Keep the calculation visible on the page.'] for context in agent.review_contexts)
    assert all(context['original_request']==review['binding']['inputs']['original_request'] for context in agent.review_contexts)
