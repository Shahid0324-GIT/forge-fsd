import json
from pathlib import Path

import pytest

from forge.autonomous_build import build_app,build_resumable
from forge.autonomous_planning import plan_app
from forge.autonomous_review import decide_plan,review_snapshot
from forge.persistence import JobStore
from forge.tasks import TaskLedger
from forge.workspace import source_fingerprint
from test_autonomous_planning import Agent,draft


class Builder(Agent):
    def __init__(self,proposal):
        super().__init__(proposal);self.edits=[];self.cancel=None
    def generate(self,schema,instruction,data,**kwargs):
        if schema.__name__=='RepairFocus':
            return schema.model_validate({'file':data['allowed_targets'][0],'cause':'Actual compiler failure','changes':['Correct the reported expression']})
        if schema.__name__=='RecoveryDecision':
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
        {'path':'app/page.tsx','owner':'frontend','purpose':'Show the calculated value'}]})
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


def test_resume_checks_current_source_without_regenerating_completed_files(setup):
    store,job,agent,boundary,review=setup;approve(store,job,review)
    paused=build_app(job,agent,store,workspace_boundary=boundary,check_runner=runner(False))
    assert paused['status']=='AUTONOMOUS_BUILD_PAUSED' and build_resumable(paused,store)
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
