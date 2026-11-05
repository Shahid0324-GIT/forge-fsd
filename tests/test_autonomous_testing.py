import hashlib
import json
from pathlib import Path

import pytest

from forge.acceptance_browser import harness_fingerprint
from forge.autonomous_build import build_app
from forge.autonomous_testing import evidence_current,test_app as run_app_tests,tests_resumable as resumable_checks
from forge.source_checks import harness_fingerprint as build_harness
from forge.tasks import TaskLedger
from forge.workspace import source_fingerprint
from test_autonomous_build import Builder,approve,runner,setup


class QAAgent(Builder):
    def __init__(self,proposal):
        super().__init__(proposal);self.qa_contexts=[];self.repair_contracts=[];self.uncovered=False;self.coverage_supported=False;self.coverage_calls=0
    def generate(self,schema,instruction,data,**kwargs):
        if schema.__name__=='AcceptanceCritique':
            return schema.model_validate({'assessed_criteria':sorted({index for case in data['proposed_suite']['scenarios'] for index in case['criteria']}),'issues':[]})
        if schema.__name__=='CoverageDecision':
            self.coverage_calls+=1
            return schema.model_validate({'can_check':self.coverage_supported,'reason':'Reload can be checked' if self.coverage_supported else 'Server restart is outside the browser protocol',
                'strategy':['visit, interact, visit again, assert initial value'] if self.coverage_supported else []})
        if schema.__name__=='AcceptanceSuite':
            self.qa_contexts.append(data)
            count=len(data['approved_design']['acceptance_criteria'])
            feedback=(data.get('proposal_feedback') or {}).get('message','')
            if self.coverage_supported and any('Coverage review found' in error for error in [feedback,*data['protocol_errors']]):self.uncovered=False
            if self.uncovered:return schema.model_validate({'scenarios':[],
                'uncovered':[{'criterion':index,'reason':'Requires database restart'} for index in range(1,count+1)]})
            return schema.model_validate({'scenarios':[{'id':'shows_result','criteria':list(range(1,count+1)),'steps':[
                {'action':'visit','path':'/'},{'action':'assert_visible','target':{'by':'text','value':'3'}}]}],
                'uncovered':[]})
        if schema.__name__=='SourceEdit' and data['repair_mode']:
            self.repair_contracts.append(data['acceptance_contract'])
            path=data['allowed_targets'][0];old=data['source'][path]
            return schema.model_validate({'tool':'write_file','path':path,
                'content':old['content']+'\n// model-proposed repair '+str(data['attempt']),
                'expected_sha256':old['sha256'],'expected_workspace_fingerprint':data['workspace_fingerprint'],'require_change':True})
        return super().generate(schema,instruction,data,**kwargs)


def build_checks(root,directory,job):
    result=runner()(root,directory,job)
    result.update(image='sha256:'+'a'*64,cleanup_errors=[],harness_fingerprint=build_harness())
    Path(result['report']).write_text(json.dumps(result),encoding='utf-8')
    return result


def browsers(outcomes,seen=None):
    def execute(root,directory,job,contract,image):
        if seen is not None:seen.append(contract['fingerprint'])
        passed=outcomes[0]
        if len(outcomes)>1:outcomes.pop(0)
        directory.mkdir(parents=True);path=directory/'report.json'
        result={'passed':passed,'job_id':job,'report':str(path),'cleanup_errors':[],'source_fingerprint':source_fingerprint(root),
            'contract_fingerprint':contract['fingerprint'],'review_fingerprint':contract['review_fingerprint'],
            'harness_fingerprint':harness_fingerprint(),'app_image':image,'browser_image':'sha256:'+'b'*64,
            'source_unchanged':True,'contract_unchanged':True,'harness_unchanged':True,'execution':{'exit_code':0 if passed else 1,'stopped':None},
            'browser':{'passed':passed,'results':[{'id':case['id'],'criteria':case['criteria'],'passed':passed,
                **({'step':2,'error':'Expected visible result was missing'} if not passed else {})} for case in contract['suite']['scenarios']]}}
        path.write_text(json.dumps(result),encoding='utf-8');return result
    return execute


@pytest.fixture
def ready(setup):
    store,job,builder,boundary,review=setup;approve(store,job,review)
    build_app(job,builder,store,workspace_boundary=boundary,check_runner=runner())
    return store,job,QAAgent(builder.proposal),boundary,review


def test_frozen_requirements_checks_feed_actual_failures_to_source_repair(ready):
    store,job,agent,boundary,review=ready;seen=[]
    result=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([False,True],seen))
    assert result['status']=='AUTONOMOUS_APP_CHECKS_PASSED'
    assert len(agent.qa_contexts)==1 and 'source' not in agent.qa_contexts[0] and 'current_source' not in agent.qa_contexts[0]
    assert agent.qa_contexts[0]['original_request']==review['binding']['inputs']['original_request']
    assert agent.repair_contracts and len(set(seen))==1 and len(seen)==2
    assert evidence_current(result,store,workspace_boundary=boundary)
    assert not any(e['status'] in {'READY','SECURITY_PASSED','PREVIEW_RUNNING'} for e in result['events'])


def test_browser_infrastructure_failure_cannot_trigger_application_source_repair(ready):
    store,job,agent,boundary,_=ready
    def unavailable(*args):
        result=browsers([False])(*args)
        result.update(error='Browser dependency image unavailable',browser={'results':[]})
        Path(result['report']).write_text(json.dumps(result),encoding='utf-8')
        return result
    result=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=unavailable)
    assert result['status']=='AUTONOMOUS_TEST_PAUSED' and not agent.repair_contracts
    assert 'restore the execution environment' in result['events'][-1]['payload']['reason']


@pytest.mark.parametrize('change',['source','contract','combined_report','browser_report','verify_revision','quality_review','quality_task'])
def test_pass_is_invalidated_when_any_final_evidence_changes(ready,change):
    store,job,agent,boundary,_=ready
    result=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    assert evidence_current(result,store,workspace_boundary=boundary)
    event=result['events'][-1]['payload'];ledger=TaskLedger(store,job)
    if change=='source':(boundary/job/'app/page.tsx').write_text('changed',encoding='utf-8')
    if change=='contract':Path(ledger.read(event['qa_task_id']).observations[-1].checks[0].report).write_text('{}',encoding='utf-8')
    if change=='combined_report':Path(event['report']).write_text('{}',encoding='utf-8')
    if change=='browser_report':Path(json.loads(Path(event['report']).read_text())['acceptance_report']).write_text('{}',encoding='utf-8')
    if change=='verify_revision':
        state=ledger.read(event['task_id']);ledger.revise(state,state.task)
    if change in {'quality_review','quality_task'}:
        qa=ledger.read(event['qa_task_id']);contract=json.loads(Path(qa.observations[-1].checks[0].report).read_text())
        reference=contract['quality_review']
        if change=='quality_review':Path(reference['report']).write_text('{}')
        else:
            child=ledger.read(reference['task_id']);ledger.revise(child,child.task)
    assert not evidence_current(store.read(job),store,workspace_boundary=boundary)


def test_saved_qa_pause_resumes_without_replanning_or_discarding_frozen_assertions(ready):
    store,job,agent,boundary,_=ready;seen=[]
    paused=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([False],seen))
    assert paused['status']=='AUTONOMOUS_TEST_PAUSED' and resumable_checks(paused,store,workspace_boundary=boundary)
    repairs=len(agent.repair_contracts)
    result=run_app_tests(job,agent,store,resume=True,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True],seen))
    assert result['status']=='AUTONOMOUS_APP_CHECKS_PASSED' and len(agent.qa_contexts)==1 and len(set(seen))==1
    assert len(agent.repair_contracts)==repairs


def test_uncovered_requirements_block_promotion_without_running_superficial_checks(ready):
    store,job,agent,boundary,_=ready;agent.uncovered=True
    result=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,
        browser_runner=lambda *_:pytest.fail('Unsupported criteria must not run superficial checks'))
    assert result['status']=='AUTONOMOUS_CHECKS_BLOCKED' and not agent.repair_contracts
    assert result['events'][-1]['payload']['uncovered'] and not evidence_current(result,store,workspace_boundary=boundary)


@pytest.fixture(params=['separate','mixed'])
def partially_covered(tmp_path,request):
    from forge.autonomous_planning import plan_app
    from forge.autonomous_review import review_snapshot
    from forge.persistence import JobStore
    from test_autonomous_planning import draft
    mixed=request.param=='mixed'
    proposal=draft().model_copy(update={'acceptance_criteria':
        ['Display the calculated result and announce it to screen readers'] if mixed else
        ['Display the calculated result','Persist state after server restart']})
    class PartialQA(QAAgent):
        def generate(self,schema,instruction,data,**kwargs):
            if schema.__name__=='AcceptanceSuite':
                return schema.model_validate({'scenarios':[{'id':'result','criteria':[1],'steps':[
                    {'action':'visit','path':'/'},{'action':'assert_visible','target':{'by':'text','value':'3'}}]}],
                    'uncovered':[{'criterion':1,'coverage':'partial','checked_behavior':'Visible calculated result',
                        'reason':'Screen reader execution unavailable'}] if mixed else
                        [{'criterion':2,'reason':'Requires server restart, outside browser protocol'}]})
            return super().generate(schema,instruction,data,**kwargs)
    agent=PartialQA(proposal);store=JobStore(tmp_path/'artifacts/jobs.sqlite3')
    job=plan_app('Display the calculated result and retain state after server restart.',agent,store)['job_id']
    approve(store,job,review_snapshot(job,store));boundary=tmp_path/'workspace'
    build_app(job,agent,store,workspace_boundary=boundary,check_runner=runner())
    return store,job,agent,boundary


@pytest.mark.parametrize('changed',[None,'source','contract','report'])
def test_supported_checks_execute_without_waiving_uncovered_requirements(partially_covered,changed):
    store,job,agent,boundary=partially_covered;seen=[]
    result=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True],seen))
    assert result['status']=='AUTONOMOUS_CHECKS_BLOCKED' and len(seen)==1
    event=result['events'][-1]['payload']
    assert event['selected_checks_passed'] and event['uncovered']
    assert not evidence_current(result,store,workspace_boundary=boundary)
    assert evidence_current(result,store,workspace_boundary=boundary,selected_only=True)
    if changed=='source':(boundary/job/'app/page.tsx').write_text('Changed after checks')
    if changed=='contract':
        qa=TaskLedger(store,job).read(event['qa_task_id'])
        Path(qa.observations[-1].checks[0].report).write_text('{}')
    if changed=='report':Path(event['report']).write_text('{}')
    if changed:assert not evidence_current(result,store,workspace_boundary=boundary,selected_only=True)
    assert not any(e['status'] in {'AUTONOMOUS_APP_CHECKS_PASSED','READY'} for e in result['events'])


def test_selected_checks_repair_against_same_contract_and_can_be_rerun(partially_covered):
    store,job,agent,boundary=partially_covered;seen=[]
    result=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([False,True],seen))
    assert result['status']=='AUTONOMOUS_CHECKS_BLOCKED' and agent.repair_contracts and len(set(seen))==1
    result=run_app_tests(job,agent,store,run_selected=True,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True],seen))
    assert len(seen)==3 and len(set(seen))==1 and result['status']=='AUTONOMOUS_CHECKS_BLOCKED'
    assert evidence_current(result,store,workspace_boundary=boundary,selected_only=True)


def test_supported_coverage_claim_is_reviewed_before_any_contract_is_frozen(ready):
    store,job,agent,boundary,_=ready;agent.uncovered=True;agent.coverage_supported=True
    result=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    assert result['status']=='AUTONOMOUS_APP_CHECKS_PASSED' and len(agent.qa_contexts)==2 and agent.coverage_calls==1
    assert 'Coverage review found' in agent.qa_contexts[-1]['proposal_feedback']['message']
    assert agent.qa_contexts[-1]['protocol_errors']==[]
    assert not any(e['status']=='AUTONOMOUS_CHECKS_BLOCKED' for e in result['events'])
    assert any(e['payload'].get('recipient')=='coverage_reviewer' for e in result['events'])


def test_blocked_coverage_can_be_re_evaluated_without_rewriting_old_contract(ready):
    store,job,agent,boundary,_=ready;agent.uncovered=True
    blocked=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    path=Path(blocked['events'][-1]['payload']['report']);original=path.read_bytes();source=source_fingerprint(boundary/job)
    agent.uncovered=False
    result=run_app_tests(job,agent,store,retry_coverage=True,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    assert result['status']=='AUTONOMOUS_APP_CHECKS_PASSED' and path.read_bytes()==original
    assert source_fingerprint(boundary/job)==source and len(agent.qa_contexts)==2


def test_resource_resume_repairs_current_failure_before_retesting_instead_of_repeating_review(ready):
    from forge.provider_errors import ProviderResourceError
    store,job,agent,boundary,_=ready;generate=agent.generate;seen=[]
    def quota(schema,*args,**kwargs):
        if schema.__name__=='RepairFocus':raise ProviderResourceError('Provider quota pause')
        return generate(schema,*args,**kwargs)
    agent.generate=quota
    paused=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([False],seen))
    assert paused['status']=='AUTONOMOUS_TEST_PAUSED' and len(seen)==1
    agent.generate=generate
    result=run_app_tests(job,agent,store,resume=True,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True],seen))
    assert result['status']=='AUTONOMOUS_APP_CHECKS_PASSED'
    assert len(agent.repair_contracts)==1 and len(seen)==2
    assert evidence_current(result,store,workspace_boundary=boundary)


@pytest.mark.parametrize('change',[None,'source','browser','build','contract'])
def test_failed_evidence_reuse_requires_current_source_contract_and_intact_reports(ready,change):
    from forge.provider_errors import ProviderResourceError
    from forge.autonomous_testing import current_failure_for_repair
    from forge.autonomous_acceptance import load_acceptance
    store,job,agent,boundary,review=ready;generate=agent.generate
    def quota(schema,*args,**kwargs):
        if schema.__name__=='RepairFocus':raise ProviderResourceError('Provider quota pause')
        return generate(schema,*args,**kwargs)
    agent.generate=quota
    result=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([False]))
    ledger=TaskLedger(store,job);pending=result['events'][-1]['payload'];state=ledger.read(pending['task_id'])
    qa=next(t for t in ledger.list() if t.task.inputs.get('stage')=='acceptance_plan')
    contract=load_acceptance(ledger,qa,review);report=json.loads(Path(state.observations[-1].checks[0].report).read_text(encoding='utf-8'))
    if change=='source':(boundary/job/'app/page.tsx').write_text('changed',encoding='utf-8')
    if change=='browser':Path(report['acceptance_report']).write_text('{}',encoding='utf-8')
    if change=='build':Path(report['build_report']).write_text('{}',encoding='utf-8')
    if change=='contract':contract={**contract,'fingerprint':'stale'}
    assert current_failure_for_repair(state,boundary/job,contract)==(change is None)


def test_recheck_keeps_frozen_contract_and_replaces_evidence_for_same_source(ready):
    store,job,agent,boundary,_=ready
    first=run_app_tests(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    before=first['events'][-1]['payload'];source=source_fingerprint(boundary/job)
    result=run_app_tests(job,agent,store,recheck=True,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    after=result['events'][-1]['payload']
    assert result['status']=='AUTONOMOUS_APP_CHECKS_PASSED' and evidence_current(result,store,workspace_boundary=boundary)
    assert source_fingerprint(boundary/job)==source==after['source_fingerprint']
    assert before['contract_fingerprint']==after['contract_fingerprint']
    assert after['verification_revision']>before['verification_revision'] and len(agent.qa_contexts)==1
    assert not agent.repair_contracts
