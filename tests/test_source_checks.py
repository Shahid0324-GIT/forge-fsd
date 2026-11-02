import json
import subprocess
from types import SimpleNamespace

import pytest

import forge.source_checks as module


@pytest.fixture
def setup(tmp_path,monkeypatch):
    root=tmp_path/'workspace';root.mkdir()
    (root/'package.json').write_text('{}',encoding='utf-8')
    (root/'package-lock.json').write_text('{}',encoding='utf-8')
    calls=[]
    monkeypatch.setattr(module.subprocess,'check_output',lambda *a,**k:'sha256:'+'a'*64)
    def cleanup(args,**_):calls.append(args);return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr(module.subprocess,'run',cleanup)
    body={'passed':True,'results':[{'name':'typecheck','exit_code':0,'stopped':None,'output':'checked'},
        {'name':'production_build','exit_code':0,'stopped':None,'output':'built'}],
        'source_lock':'b'*64,'image_lock':'b'*64}
    def execute(args,**_):
        calls.append(args)
        return {'command':args,'exit_code':0,'stopped':None,'output':'FORGE_SOURCE_REPORT:'+json.dumps(body)}
    monkeypatch.setattr(module,'bounded_command',execute)
    return root,tmp_path/'reports',body,calls


def test_generic_checks_are_isolated_and_do_not_claim_behavior_coverage(setup):
    root,directory,_,calls=setup
    report=module.run_source_checks(root,directory,'1'*32)
    assert report['passed'] and report['source_unchanged'] and report['harness_unchanged']
    assert report['coverage']['application_behavior']=='NOT_TESTED'
    command=calls[0]
    assert '--network=none' in command and '--read-only' in command and '--pull=never' in command
    assert 'forge.role=verification' in command
    assert any('target=/trusted/source-checks.mjs,readonly' in arg for arg in command)
    assert not any('target=/trusted,readonly' in arg for arg in command)
    assert calls[-1][:3]==['docker','rm','--force']


@pytest.mark.parametrize('change',['missing_check','bad_lock','lock_mismatch','exit_failure'])
def test_incomplete_or_mismatched_evidence_cannot_pass(setup,change,monkeypatch):
    root,directory,body,_=setup
    if change=='missing_check':body['results'].pop()
    if change=='bad_lock':body.pop('source_lock');body.pop('image_lock')
    if change=='lock_mismatch':body['image_lock']='c'*64
    if change=='exit_failure':body['results'][0]['exit_code']=1
    assert not module.run_source_checks(root,directory,'1'*32)['passed']


def test_source_changes_during_execution_invalidate_passed_checks(setup,monkeypatch):
    root,directory,_,_=setup
    fingerprints=iter(['a'*64,'b'*64])
    monkeypatch.setattr(module,'source_fingerprint',lambda _:next(fingerprints))
    report=module.run_source_checks(root,directory,'1'*32)
    assert not report['passed'] and not report['source_unchanged']


def test_cleanup_failure_is_reported_and_blocks_pass(setup,monkeypatch):
    root,directory,_,_=setup
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1,stdout='',stderr='cleanup denied'))
    report=module.run_source_checks(root,directory,'1'*32)
    assert not report['passed'] and report['cleanup_errors']==['cleanup denied']


def test_unavailable_image_has_actual_command_exit_and_output(setup,monkeypatch):
    root,directory,_,calls=setup
    def fail(args,**_):raise subprocess.CalledProcessError(1,args,output='No such image: forge-task-deps:local')
    monkeypatch.setattr(module.subprocess,'check_output',fail)
    report=module.run_source_checks(root,directory,'1'*32)
    assert not report['passed'] and not calls
    assert report['environment_failure']['exit_code']==1
    assert report['environment_failure']['command'][:3]==['docker','image','inspect']
    assert 'No such image' in report['environment_failure']['output']
