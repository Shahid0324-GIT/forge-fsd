import json
import hashlib

import pytest

from forge.preview import check_preview_gate, cleanup, start_preview
from forge.workspace import source_fingerprint
from test_security import passing_checks
from test_autonomous_testing import ready,build_checks,browsers
from test_autonomous_build import setup


def preview_fixture(tmp_path):
    root=tmp_path/'workspace';root.mkdir();(root/'app.ts').write_text('source')
    fingerprint=source_fingerprint(root)
    report=tmp_path/'security.json'
    from forge.preview import PROJECT
    checks=passing_checks();checks['pip_audit']['lock_sha256']=hashlib.sha256((PROJECT/'requirements.lock.txt').read_bytes()).hexdigest()
    report.write_text(json.dumps({'source_fingerprint':fingerprint,'source_unchanged':True,'checks':checks}))
    record={'status':'SECURITY_PASSED','events':[
        {'status':'FUNCTIONALLY_VERIFIED','payload':{'source_fingerprint':fingerprint}},
        {'status':'SECURITY_PASSED','payload':{'source_fingerprint':fingerprint,'report':str(report)}}]}
    return root,report,record


def test_preview_requires_explicit_human_approval():
    with pytest.raises(ValueError,match='approval'):
        start_preview('job',None,approved=False)


def test_preview_checks_current_source_and_every_security_check(tmp_path):
    root,path,record=preview_fixture(tmp_path)
    assert check_preview_gate(record,root)==source_fingerprint(root)
    report=json.loads(path.read_text());report['checks']['semgrep']['status']='UNVERIFIED'
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError,match='incomplete'):
        check_preview_gate(record,root)


def test_preview_refuses_stale_functional_evidence(tmp_path):
    root,path,record=preview_fixture(tmp_path)
    (root/'app.ts').write_text('changed')
    with pytest.raises(ValueError,match='functional'):
        check_preview_gate(record,root)


def test_preview_cannot_start_without_security_pass(tmp_path):
    root,path,record=preview_fixture(tmp_path);record['status']='SECURITY_BLOCKED'
    with pytest.raises(ValueError,match='security'):
        check_preview_gate(record,root)


def test_cleanup_cannot_remove_unrelated_container(monkeypatch):
    import forge.preview as module
    monkeypatch.setattr(module,'docker',lambda *args:json.dumps([{'Config':{'Labels':{'forge.job':'other','forge.role':'preview'}}}]))
    with pytest.raises(ValueError,match='unrelated'):
        cleanup({'container':'forge-preview-example','network':'forge-preview-net-example'},'job')


def test_resource_lookup_ignores_readiness_and_permission_status_strings():
    from forge.preview import preview_resources
    resources={'container':'forge-preview-example'}
    record={'events':[{'status':'PREVIEW_STOPPED','payload':{'preview':resources}},
        {'status':'AUTONOMOUS_BUILD_CHECKS_PASSED','payload':{'preview':'NOT_APPROVED'}}]}
    assert preview_resources(record)==resources
    assert preview_resources({'events':record['events'][1:]}) is None


@pytest.fixture
def autonomous_preview(ready,monkeypatch):
    import forge.preview as module
    from forge.autonomous_testing import test_app
    store,job,agent,boundary,_=ready
    test_app(job,agent,store,workspace_boundary=boundary,check_runner=build_checks,browser_runner=browsers([True]))
    monkeypatch.setattr(module,'PROJECT',boundary.parent)
    return store,job,boundary


@pytest.mark.parametrize('race',[None,'source','contract'])
def test_autonomous_preview_uses_complete_evidence_and_rechecks_after_startup(autonomous_preview,monkeypatch,race):
    import forge.preview as module
    from forge.tasks import TaskLedger
    store,job,boundary=autonomous_preview;commands=[];urls=[];launches=[]
    def docker(*args):
        commands.append(args)
        if args[0]=='inspect':return json.dumps([{'NetworkSettings':{'Ports':{'3000/tcp':[{'HostIp':'127.0.0.1','HostPort':'45555'}]}},'Id':'fixture','State':{'Pid':123}}])
        if args[0] in {'container','network'} and args[1]=='inspect':return json.dumps([{'Config':{'Labels':{'forge.job':job,'forge.role':'preview'}},'Labels':{'forge.job':job,'forge.role':'preview'}}])
        return ''
    monkeypatch.setattr(module,'docker',docker)
    def launch(args,**kwargs):launches.append(args);return {'exit_code':0,'stopped':None,'output':''}
    monkeypatch.setattr(module,'bounded_command',launch)
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*_):pass
    def open_url(url,**_):
        urls.append(url)
        if race=='source':(boundary/job/'app/page.tsx').write_text('changed during startup')
        if race=='contract':
            qa=next(t for t in TaskLedger(store,job).list() if t.task.inputs.get('stage')=='acceptance_plan')
            __import__('pathlib').Path(qa.observations[-1].checks[0].report).write_text('{}')
        return Response()
    monkeypatch.setattr(module,'urlopen',open_url)
    result=module.start_preview(job,store,approved=True)
    assert result['status']==('PREVIEW_FAILED' if race else 'PREVIEW_RUNNING')
    assert all('/api/tasks' not in url for url in urls)
    assert launches[1][-3:] == ['sha256:'+'a'*64,'node','/proxy.mjs']
    if race:assert any(args[:2]==('rm','--force') for args in commands)
    else:
        payload=result['events'][-1]['payload']
        assert payload['url']=='http://127.0.0.1:45555' and payload['smoke_tests']=={'/':200}
        assert 'Security' in payload['verification_scope']
        assert module.stop_preview(job,store)['status']=='PREVIEW_STOPPED'


@pytest.mark.parametrize('invalid',['stale','partial'])
def test_autonomous_preview_rejects_stale_or_partial_evidence_before_docker(autonomous_preview,monkeypatch,invalid):
    import forge.preview as module
    store,job,boundary=autonomous_preview
    if invalid=='stale':(boundary/job/'app/page.tsx').write_text('changed')
    else:store.event(job,'AUTONOMOUS_CHECKS_BLOCKED',{'selected_checks_passed':True})
    monkeypatch.setattr(module,'docker',lambda *_:pytest.fail('Invalid evidence must not start Docker'))
    with pytest.raises(ValueError,match='current'):module.start_preview(job,store,approved=True)
