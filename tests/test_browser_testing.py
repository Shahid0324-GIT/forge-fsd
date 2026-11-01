import json
import subprocess

import pytest

import forge.browser_testing as browser
from forge.persistence import JobStore
from test_general_apps import calculator_spec,calculator_plan


@pytest.mark.parametrize('network_message',['No such network: {name}','network {name} not found'])
def test_browser_cleanup_accepts_already_removed_networks(monkeypatch,network_message):
    resources={'app':'forge-browser-app-'+'a'*12,'browser':'forge-browser-check-'+'a'*12,'network':'forge-browser-net-'+'a'*12}
    calls=[]
    def docker(*args):
        calls.append(args)
        kind,_,name=args
        message=network_message.format(name=name) if kind=='network' else f'No such container: {name}'
        raise subprocess.CalledProcessError(1,args,output='Error response from daemon: '+message)
    monkeypatch.setattr(browser,'docker',docker)
    browser.cleanup_browser(resources,'b'*32)
    assert len(calls)==3 and all(args[1]=='inspect' for args in calls)


def test_browser_cleanup_does_not_ignore_daemon_errors(monkeypatch):
    resources={'app':'forge-browser-app-'+'a'*12,'browser':'forge-browser-check-'+'a'*12,'network':'forge-browser-net-'+'a'*12}
    def docker(*args):raise subprocess.CalledProcessError(1,args,output='Cannot connect to the Docker daemon: no such file or directory')
    monkeypatch.setattr(browser,'docker',docker)
    with pytest.raises(subprocess.CalledProcessError):browser.cleanup_browser(resources,'b'*32)


def passed():
    return {'profile':browser.PROFILE,'source_fingerprint':'a'*64,'source_unchanged':True,
            'harness_fingerprint':browser.harness_fingerprint(),
            'execution':{'exit_code':0,'stopped':None},
            'browser':{'passed':True,'results':[{'name':name,'passed':True} for name in sorted(browser.CASES)]}}


def test_browser_profile_is_explicitly_scoped_to_converter_contract():
    spec=calculator_spec();plan=calculator_plan()
    record={'events':[{'status':'PLAN_REVIEW','payload':{'requirements':spec,'plan':plan}}]}
    assert browser.profile_for(record) is None
    spec['title']='Temperature converter';plan['routes']=['POST /api/convert']
    assert browser.profile_for(record)==browser.PROFILE
    spec['database']='sqlite'
    assert browser.profile_for(record) is None


def test_browser_gate_requires_current_complete_execution_after_opt_in(tmp_path):
    record={'events':[]};fp='a'*64
    assert browser.browser_gate(record,fp)  # Missing coverage is not labeled a passing test.
    record['events'].append({'status':'AUTOMATED_BROWSER_STARTED','payload':{'source_fingerprint':fp}})
    assert not browser.browser_gate(record,fp)
    path=tmp_path/'browser.json';path.write_text(json.dumps(passed()))
    record['events'].append({'status':'AUTOMATED_BROWSER_PASSED','payload':{'source_fingerprint':fp,'report':str(path)}})
    assert browser.browser_gate(record,fp)
    assert not browser.browser_gate(record,'b'*64)
    report=passed();report['harness_fingerprint']='changed';path.write_text(json.dumps(report))
    assert not browser.browser_gate(record,fp)
    path.write_text(json.dumps(passed()))
    record['events'].append({'status':'AUTOMATED_BROWSER_FAILED','payload':{'source_fingerprint':fp}})
    assert not browser.browser_gate(record,fp)


@pytest.mark.parametrize('change',[
    lambda r:r['browser']['results'].pop(),
    lambda r:r['browser']['results'][0].update(passed=False),
    lambda r:r['execution'].update(stopped='timeout'),
    lambda r:r.update(source_unchanged=False),
    lambda r:r.update(cleanup_errors='Could not stop owned container'),
])
def test_partial_or_unverified_browser_result_cannot_pass(change):
    report=passed();change(report)
    assert not browser.passed_report(report)


def test_browser_cleanup_refuses_unrelated_resources(monkeypatch):
    calls=[]
    def docker(*args):
        calls.append(args)
        return json.dumps([{'Config':{'Labels':{'forge.job':'another-job','forge.role':'browser_verification'}}}])
    monkeypatch.setattr(browser,'docker',docker)
    resources={'app':'forge-browser-app-'+'a'*12,'browser':'forge-browser-check-'+'a'*12,'network':'forge-browser-net-'+'a'*12}
    with pytest.raises(ValueError,match='unrelated'):browser.cleanup_browser(resources,'b'*32)
    assert all('rm' not in call for call in calls)


def test_browser_evidence_is_bound_to_the_verified_app_image(tmp_path):
    fp='a'*64;image='sha256:'+'1'*64
    functional=tmp_path/'functional.json';functional.write_text(json.dumps({'image':image}))
    report=passed();report['app_image']=image
    path=tmp_path/'browser.json';path.write_text(json.dumps(report))
    record={'events':[{'status':'FUNCTIONALLY_VERIFIED','payload':{'source_fingerprint':fp,'report':str(functional)}},
                      {'status':'AUTOMATED_BROWSER_PASSED','payload':{'source_fingerprint':fp,'report':str(path)}}]}
    assert browser.browser_gate(record,fp)
    functional.write_text(json.dumps({'image':'sha256:'+'2'*64}))
    assert not browser.browser_gate(record,fp)


def test_browser_output_cannot_escape_artifacts(tmp_path,monkeypatch):
    monkeypatch.setattr(browser,'PROJECT',tmp_path)
    root=tmp_path/'workspace';root.mkdir();(root/'package.json').write_text('{}')
    with pytest.raises(ValueError,match='artifacts'):
        browser.run_browser_checks(root,tmp_path/'elsewhere','a'*32)


def test_unsupported_app_does_not_stop_its_preview(tmp_path):
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    store.event(job,'PLAN_REVIEW',{'requirements':calculator_spec(),'plan':calculator_plan()})
    store.event(job,'PREVIEW_RUNNING',{})
    with pytest.raises(ValueError,match='profile'):browser.browser_job(job,store)
    assert store.read(job)['status']=='PREVIEW_RUNNING'


def test_browser_failure_blocks_preview_despite_passing_security(tmp_path):
    from test_preview import preview_fixture
    from forge.preview import check_preview_gate
    root,path,record=preview_fixture(tmp_path)
    fp=record['events'][0]['payload']['source_fingerprint']
    record['events'].append({'status':'AUTOMATED_BROWSER_FAILED','payload':{'source_fingerprint':fp}})
    with pytest.raises(ValueError,match='Automated browser'):check_preview_gate(record,root)


def test_browser_failure_prevents_positive_readiness_assessment(tmp_path,monkeypatch):
    import forge.reporting as reporting
    from test_reporting import NotesAgent
    from test_security import passing_checks
    from forge.workspace import source_fingerprint
    monkeypatch.setattr(reporting,'PROJECT',tmp_path)
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    root=tmp_path/'workspace'/job;root.mkdir(parents=True);(root/'app.ts').write_text('source')
    fp=source_fingerprint(root)
    functional=tmp_path/'functional.json';functional.write_text(json.dumps({'source_fingerprint':fp,'source_unchanged':True,
        'execution':{'exit_code':0},'checks':{'passed':True,'results':[{'name':name,'exit_code':0} for name in ['typecheck','production_build','acceptance']]}}))
    security=tmp_path/'security.json';security.write_text(json.dumps({'checks':passing_checks(),'source_unchanged':True}))
    store.event(job,'PLAN_REVIEW',{'requirements':{'spec_version':2,'database':'none'},'plan':{}})
    store.event(job,'FUNCTIONALLY_VERIFIED',{'source_fingerprint':fp,'report':str(functional)})
    store.event(job,'SECURITY_PASSED',{'source_fingerprint':fp,'report':str(security)})
    record=reporting.write_report(job,NotesAgent(),store)
    assert json.loads(open(record['events'][-1]['payload']['report']).read())['assessment']=='LOCALLY_VERIFIED_WITH_LIMITATIONS'
    failed=tmp_path/'browser.json';failed.write_text(json.dumps({'profile':browser.PROFILE,'passed':False,'browser':{'results':[]}}))
    store.event(job,'AUTOMATED_BROWSER_FAILED',{'source_fingerprint':fp,'report':str(failed)},update_status=False)
    record=reporting.write_report(job,NotesAgent(),store)
    assert json.loads(open(record['events'][-1]['payload']['report']).read())['assessment']=='UNVERIFIED'
