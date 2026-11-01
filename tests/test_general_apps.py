import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from forge.builders import build_job
from forge.persistence import JobStore
from forge.schemas import RequirementsDocument,ImplementationPlan,validate_app_contract
from forge.workflow import run_job,resume_job
from forge.workspace import write_owned,plan_owners,source_fingerprint


def calculator_spec():
    return {'spec_version':2,'title':'Tip calculator','database':'none','pages':['/'],
            'entities':[],'assumptions':['Single-user local app'],'open_questions':[],
            'acceptance_criteria':['Compute tip','Compute total','Compute per-person total','Reject invalid amounts'],
            'scenarios':[
                {'name':'Calculate tip','phase':'functional','steps':[{'method':'POST','path':'/api/calculate','body_json':'{"bill":100,"tipPercent":10,"people":2}','status':200,'expect_json':'{"tip":10,"total":110,"perPerson":55}'}]},
                {'name':'Reject invalid amount','phase':'functional','steps':[{'method':'POST','path':'/api/calculate','body_json':'{"bill":-1,"tipPercent":10,"people":2}','status':400}]}]}


def calculator_plan():
    return {'spec_version':2,'framework':'nextjs-app-router','database':'none',
            'routes':['POST /api/calculate'],
            'tasks':[{'owner':'frontend','objective':'Build calculator form','files':['app/page.tsx'],
                      'contract':'POST /api/calculate with bill, tipPercent, people; render tip, total, perPerson.'},
                     {'owner':'backend','objective':'Implement calculation','files':['app/api/calculate/route.ts'],
                      'contract':'Export POST(Request): Promise<Response>; JSON bill, tipPercent, people -> tip, total, perPerson. Invalid input returns 400.'}],
            'verification':['Typecheck','Production build','Approved HTTP acceptance']}


@pytest.mark.parametrize('title',['Tip calculator','Quiz scorer','Unit converter'])
def test_non_task_domains_preserve_contract(title):
    data=calculator_spec();data['title']=title
    req=RequirementsDocument.model_validate(data);plan=ImplementationPlan.model_validate(calculator_plan())
    validate_app_contract(req,plan)
    assert req.title==title
    assert plan_owners(plan)['backend']=={'app/api/calculate/route.ts'}


@pytest.mark.parametrize('change',['no_behavior','no_negative','missing_persistence','foreign_url'])
def test_incomplete_or_nonlocal_test_contract_is_rejected(change):
    data=calculator_spec()
    if change=='no_behavior':data['scenarios'][0]['steps'][0].pop('expect_json')
    if change=='no_negative':data['scenarios'][1]['steps'][0]['status']=200
    if change=='missing_persistence':
        data['database']='sqlite'
        data['entities']=[{'name':'expense','fields':[{'name':'amount','kind':'number','required':True,'constraints':'positive'}],'relationships':''}]
    if change=='foreign_url':data['scenarios'][0]['steps'][0]['path']='//example.com'
    with pytest.raises(ValidationError):RequirementsDocument.model_validate(data)


def test_planned_api_must_cover_approved_acceptance():
    data=calculator_plan();data['routes']=['POST /api/other'];data['tasks'][1]['files']=['app/api/other/route.ts']
    with pytest.raises(ValueError,match='Acceptance request'):
        validate_app_contract(RequirementsDocument.model_validate(calculator_spec()),ImplementationPlan.model_validate(data))


@pytest.mark.parametrize('target',['app/layout.tsx','app/api/health/route.ts','lib/../../policy.ts','package.json'])
def test_generic_plan_cannot_own_controlled_files(target):
    data=calculator_plan();data['tasks'][1]['files']=[target]
    with pytest.raises(ValidationError):ImplementationPlan.model_validate(data)


def test_dynamic_writer_does_not_inherit_legacy_permissions(tmp_path):
    owners=plan_owners(ImplementationPlan.model_validate(calculator_plan()))
    write_owned(tmp_path,'backend','app/api/calculate/route.ts','export const POST=()=>{};',owners)
    for target in ['lib/tasks.ts','app/page.tsx','../../escape.ts']:
        with pytest.raises(ValueError):write_owned(tmp_path,'backend',target,'unapproved',owners)


def test_generic_nested_build_uses_approved_manifest_and_minimal_scaffold(tmp_path,monkeypatch):
    import forge.builders as module
    from pathlib import Path
    # Use the real fixed scaffold; substitute only the generated implementation.
    project=Path(__file__).resolve().parents[1]
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    import shutil
    shutil.copytree(project/'templates/task-app',tmp_path/'templates/task-app')
    class Agents:
        def __init__(self):self.generated=[]
        def requirements(self,_):return calculator_spec()
        def plan(self,_,**kwargs):return calculator_plan()
        def acceptance(self,*_):return {'database':'none','scenarios':calculator_spec()['scenarios']}
        def build_app_file(self,owner,file,plan,requirements,root):
            assert requirements['title']=='Tip calculator'
            self.generated.append((owner,file))
            return {'content':'export default function Page(){return null;}' if owner=='frontend' else 'export async function POST(){return Response.json({});}'}
    agents=Agents();store=JobStore(tmp_path/'jobs.db')
    record=run_job('Create a tip calculator',agents,store)
    statuses=[event['status'] for event in record['events']]
    assert statuses.index('PLANNING')<statuses.index('TEST_PLANNING')<statuses.index('PLAN_REVIEW')
    fingerprint=record['events'][-1]['payload']['fingerprint']
    record=resume_job(record['job_id'],{'approved':True,'fingerprint':fingerprint},None,store)
    record=build_job(record['job_id'],agents,store)
    assert record['status']=='GENERATED_UNVERIFIED'
    assert agents.generated==[('backend','app/api/calculate/route.ts'),('frontend','app/page.tsx')]
    root=tmp_path/'workspace'/record['job_id']
    assert (root/'app/api/health/route.ts').exists()
    assert not (root/'lib/tasks.ts').exists()
    assert not (root/'app/api/tasks').exists()
    assert 'task manager' not in (root/'app/layout.tsx').read_text()


def test_generic_repair_cannot_select_unapproved_files(tmp_path,monkeypatch):
    import forge.repair as module
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    root=tmp_path/'workspace'/job;root.mkdir(parents=True);(root/'example.ts').write_text('broken')
    store.event(job,'PLAN_REVIEW',{'requirements':calculator_spec(),'plan':calculator_plan()})
    report=tmp_path/'failure.json';report.write_text(json.dumps({'source_fingerprint':source_fingerprint(root),'checks':{'results':[{'name':'acceptance','exit_code':1,'output':'wrong total'}]}}))
    store.event(job,'VERIFICATION_FAILED',{'report':str(report)})
    class QA:
        def generate(self,*args,**kwargs):return {'diagnosis':'wrong total','recommendation':'tamper with test','files':['../../tests/acceptance/application.mjs']}
    with pytest.raises(ValueError,match='ownership'):module.repair_job(job,QA(),store)
    assert (root/'example.ts').read_text()=='broken'


def test_sqlite_specification_and_restart_capture_contract():
    data=calculator_spec();data.update(title='Expense tracker',database='sqlite',entities=[
        {'name':'expense','fields':[{'name':'amount','kind':'number','required':True,'constraints':'positive'}],'relationships':''}])
    data['scenarios']=[
        {'name':'Create expense','phase':'functional','steps':[{'method':'POST','path':'/api/expenses','body_json':'{"amount":12.5}','status':201,'expect_json':'{"amount":12.5}','save_as':'expense_id','save_pointer':'/id'}]},
        {'name':'Invalid expense','phase':'functional','steps':[{'method':'POST','path':'/api/expenses','body_json':'{"amount":-1}','status':400}]},
        {'name':'Persistent expense','phase':'restart','steps':[{'method':'GET','path':'/api/expenses/{{expense_id}}','status':200,'expect_json':'{"amount":12.5}'}]}]
    plan=calculator_plan();plan.update(database='sqlite',routes=['POST /api/expenses','GET /api/expenses/{id}'])
    plan['tasks'][1]['files']=['app/api/expenses/route.ts','app/api/expenses/[id]/route.ts']
    validate_app_contract(RequirementsDocument.model_validate(data),ImplementationPlan.model_validate(plan))


def test_model_selection_is_persisted_and_not_an_arbitrary_provider():
    from forge.schemas import ApplicationRequest
    from forge.models import job_model
    assert ApplicationRequest(description='Create a small calculator',model='qwen2.5-coder:7b').model.endswith('7b')
    with pytest.raises(ValidationError):ApplicationRequest(description='Create a small calculator',model='https://foreign-provider')
    assert job_model({'events':[{'status':'RECEIVED','payload':{'model':'qwen2.5-coder:7b'}}]})=='qwen2.5-coder:7b'
    assert job_model({'events':[]})=='qwen2.5-coder:3b'


def test_successful_input_fixture_cannot_be_empty():
    data=calculator_spec();data['scenarios'][0]['steps'][0]['body_json']=''
    with pytest.raises(ValidationError,match='explicit JSON input'):RequirementsDocument.model_validate(data)


def test_qa_rejects_forward_capture_and_vacuous_restart_checks():
    from forge.schemas import AppAcceptancePlan
    data=calculator_spec()
    data['scenarios'][0]['steps'][0]['body_json']='{"bill":"{{missing_id}}"}'
    with pytest.raises(ValidationError,match='before it is saved'):
        AppAcceptancePlan(database='none',scenarios=data['scenarios'])
    data=calculator_spec()
    data['scenarios'].append({'name':'Empty restart','phase':'restart','steps':[{'method':'GET','path':'/api/items','status':200,'expect_json':'[]'}]})
    with pytest.raises(ValidationError,match='stored JSON data'):
        AppAcceptancePlan(database='sqlite',scenarios=data['scenarios'])


def test_coding_context_keeps_contracts_and_omits_whole_oversized_files(tmp_path):
    from forge.workspace import app_coding_context
    requirements=RequirementsDocument.model_validate(calculator_spec()).model_dump()
    plan=ImplementationPlan.model_validate(calculator_plan()).model_dump()
    source=tmp_path/'app/api/calculate/route.ts';source.parent.mkdir(parents=True);source.write_text('x'*20000)
    result=app_coding_context(requirements,plan,tmp_path,'app/page.tsx',limit=5000)
    assert result['existing_source']=={}
    assert result['context_omitted']==['app/api/calculate/route.ts']
    assert result['requirements']['acceptance_examples'][0]['steps'][0]['input']['bill']==100
    assert result['plan']==plan
    with pytest.raises(ValueError,match='contracts exceed'):
        app_coding_context(requirements,plan,tmp_path,'app/page.tsx',limit=100)


def test_model_architecture_schema_requires_one_task_per_owner():
    from forge.schemas import AppImplementationPlan
    data=calculator_plan()
    assert len(AppImplementationPlan.model_validate(data).tasks)==2
    data['tasks'][0]['owner']='backend'
    with pytest.raises(ValidationError):AppImplementationPlan.model_validate(data)


def test_failed_qa_planning_resumes_only_qa_and_still_waits_for_approval(tmp_path):
    from forge.workflow import retry_planning
    class Agents:
        def __init__(self):self.calls=[];self.failed=False
        def requirements(self,_):self.calls.append('requirements');return calculator_spec()
        def plan(self,*args,**kwargs):self.calls.append('architect');return calculator_plan()
        def acceptance(self,*args):
            self.calls.append('qa')
            if not self.failed:self.failed=True;raise ValueError('Synthetic QA failure')
            return {'database':'none','scenarios':calculator_spec()['scenarios']}
    agents=Agents();store=JobStore(tmp_path/'jobs.db')
    record=run_job('Build a small calculator',agents,store)
    assert record['status']=='FAILED'
    record=retry_planning(record['job_id'],agents,store)
    assert record['status']=='PLAN_REVIEW'
    assert agents.calls==['requirements','architect','qa','qa']
    assert not any(e['status']=='APPROVED' for e in record['events'])
    with pytest.raises(ValueError,match='pre-review'):retry_planning(record['job_id'],agents,store)


def test_structured_capture_bindings_require_existing_values_and_prior_capture():
    from forge.schemas import AppAcceptancePlan
    data=calculator_spec()
    data['scenarios'][0]['steps'][0].update(save_as='record_id',save_pointer='/id')
    data['scenarios'][1]['steps'][0].update(body_bindings=[{'pointer':'/bill','capture':'record_id'}])
    assert AppAcceptancePlan(database='none',scenarios=data['scenarios'])
    data['scenarios'][1]['steps'][0]['body_bindings'][0]['pointer']='/absent'
    with pytest.raises(ValidationError,match='existing JSON'):AppAcceptancePlan(database='none',scenarios=data['scenarios'])


def test_native_qa_json_serialization_preserves_values():
    from forge.schemas import NativeAcceptancePlan
    data=calculator_spec()
    native=[]
    for scenario in data['scenarios']:
        steps=[]
        for step in scenario['steps']:
            steps.append({**{key:step[key] for key in ['method','path','status']},
                          'body':json.loads(step['body_json']),
                          'expected':json.loads(step['expect_json']) if step.get('expect_json') else None})
        native.append({'name':scenario['name'],'phase':scenario['phase'],'steps':steps})
    result=NativeAcceptancePlan(database='none',scenarios=native).to_plan()
    assert json.loads(result.scenarios[0].steps[0].body_json)=={'bill':100,'tipPercent':10,'people':2}
    assert json.loads(result.scenarios[0].steps[0].expect_json)['perPerson']==55


def test_review_revision_invalidates_old_approval_and_preserves_history(tmp_path):
    from test_workflow import FakeAgents
    from forge.workflow import revise_review
    store=JobStore(tmp_path/'jobs.db');record=run_job('Build a small task app',FakeAgents(),store)
    review=record['events'][-1]['payload'];old=review['fingerprint'];requirements=review['requirements']
    requirements['title']='Reviewer corrected title'
    record=revise_review(record['job_id'],requirements,review['plan'],'Correct the proposed title',store)
    current=record['events'][-1]['payload'];assert current['previous_fingerprint']==old
    assert len([e for e in record['events'] if e['status']=='PLAN_REVIEW'])==2
    with pytest.raises(ValueError,match='Stale approval'):
        resume_job(record['job_id'],{'approved':True,'fingerprint':old},None,store)
    record=resume_job(record['job_id'],{'approved':True,'fingerprint':current['fingerprint']},None,store)
    assert record['status']=='APPROVED'


def test_dependency_preflight_rejects_extra_packages_and_import_escapes(tmp_path):
    from forge.workspace import unsupported_imports
    code="import {open} from 'sqlite'; import 'react-toastify/styles.css'; import {x} from '@/../../escape'; import {DatabaseSync} from 'node:sqlite'; import React from 'react';"
    assert unsupported_imports(tmp_path,'app/page.tsx',code)==['@/../../escape','react-toastify/styles.css','sqlite']


def test_builder_retries_unsupported_imports_without_accepting_them(tmp_path):
    from forge.agents import OllamaAgents
    from forge.workspace import FileOperation
    agents=OllamaAgents.__new__(OllamaAgents);calls=[]
    def generate(*args,**kwargs):
        calls.append(args[2].copy())
        return FileOperation(content="import {open} from 'sqlite';" if len(calls)==1 else 'export default function Page(){return null;}')
    agents.generate=generate
    result=agents.build_app_file('frontend','app/page.tsx',ImplementationPlan.model_validate(calculator_plan()).model_dump(),RequirementsDocument.model_validate(calculator_spec()).model_dump(),tmp_path)
    assert 'sqlite' not in result.content
    assert calls[1]['generation_feedback']['rejected_imports']==['sqlite']
    assert not (tmp_path/'app/page.tsx').exists()


def test_framework_normalization_adds_only_missing_client_directive():
    from forge.workspace import normalize_app_source
    code="import {useState} from 'react'; export default function Page(){return useState(0)[0];}"
    corrected=normalize_app_source('app/page.tsx',code)
    assert corrected=='"use client";\n'+code
    assert normalize_app_source('app/page.tsx',corrected)==corrected
    assert normalize_app_source('app/api/example/route.ts',code)==code
    assert normalize_app_source('app/page.tsx','export default function Page(){return null;}')=='export default function Page(){return null;}'
    with pytest.raises(ValueError,match='server/client'):
        normalize_app_source('app/page.tsx',code+"\nconst secret=process.env.SECRET;")
    assert normalize_app_source('lib/example.ts','```typescript\nexport const value=1;\n```')=='export const value=1;\n'
    assert normalize_app_source('app/page.tsx',code+"\nimport type {Item} from '@/lib/types';").startswith('"use client";')


def test_preview_cleanup_tolerates_only_already_removed_owned_resource(monkeypatch):
    import subprocess
    import forge.preview as module
    name='forge-preview-proxy-example'
    def fake_docker(*args):
        if args[0]=='container':return json.dumps([{'Config':{'Labels':{'forge.job':'job','forge.role':'preview'}}}])
        raise subprocess.CalledProcessError(1,args,output='Error response from daemon: No such container: '+name)
    monkeypatch.setattr(module,'docker',fake_docker)
    module.cleanup({'proxy':name},'job')
    def broken_docker(*args):
        if args[0]=='container':return json.dumps([{'Config':{'Labels':{'forge.job':'job','forge.role':'preview'}}}])
        raise subprocess.CalledProcessError(1,args,output='permission denied')
    monkeypatch.setattr(module,'docker',broken_docker)
    with pytest.raises(subprocess.CalledProcessError):module.cleanup({'proxy':name},'job')


def test_generic_verification_rejects_unapproved_contract_before_execution(tmp_path,monkeypatch):
    import forge.verification as module
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    root=tmp_path/'workspace'/job;root.mkdir(parents=True);(root/'page.tsx').write_text('source')
    store.event(job,'PLAN_REVIEW',{'requirements':calculator_spec(),'plan':calculator_plan()})
    store.event(job,'GENERATED_UNVERIFIED',{})
    with pytest.raises(ValueError,match='approved application contract'):module.verify_job(job,store)


def test_cross_file_ownership_checks_include_case_collisions():
    data=calculator_plan();data['tasks'][0]['files']=['app/page.tsx','app/Page.tsx']
    with pytest.raises(ValidationError):ImplementationPlan.model_validate(data)


@pytest.mark.parametrize('database,extra,expected',[('none',[],'LOCALLY_VERIFIED_WITH_LIMITATIONS'),('sqlite',[],'UNVERIFIED'),('sqlite',['persistence_restart'],'UNVERIFIED'),('sqlite',['persistence_restart','database_integrity'],'LOCALLY_VERIFIED_WITH_LIMITATIONS')])
def test_readiness_requires_restart_only_for_persistent_apps(tmp_path,monkeypatch,database,extra,expected):
    import forge.reporting as module
    from test_reporting import NotesAgent
    from test_security import passing_checks
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    root=tmp_path/'workspace'/job;root.mkdir(parents=True);(root/'source.ts').write_text('source')
    fingerprint=source_fingerprint(root)
    store.event(job,'PLAN_REVIEW',{'requirements':{'spec_version':2,'database':database}})
    functional=tmp_path/'functional.json';functional.write_text(json.dumps({
        'source_fingerprint':fingerprint,'source_unchanged':True,'execution':{'exit_code':0},
        'checks':{'passed':True,'results':[{'name':name,'exit_code':0} for name in ['typecheck','production_build','acceptance',*extra]]}}))
    security=tmp_path/'security.json';security.write_text(json.dumps({'checks':passing_checks(),'source_unchanged':True}))
    store.event(job,'FUNCTIONALLY_VERIFIED',{'report':str(functional),'source_fingerprint':fingerprint})
    store.event(job,'SECURITY_PASSED',{'report':str(security),'source_fingerprint':fingerprint})
    result=module.write_report(job,NotesAgent(),store)
    report=json.loads(Path(result['events'][-1]['payload']['report']).read_text())
    assert report['assessment']==expected
