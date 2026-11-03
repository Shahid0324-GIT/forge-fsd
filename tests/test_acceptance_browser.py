import hashlib
import json

import pytest

import forge.acceptance_browser as module
from test_autonomous_acceptance import proposal


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    monkeypatch.setattr(module,'harness_fingerprint',lambda:'a'*64)
    root=tmp_path/'workspace';root.mkdir();(root/'package.json').write_text('{}')
    directory=tmp_path/'artifacts/check';path=tmp_path/'contract.json'
    packet={'version':1,'job_id':'c'*32,'task_id':'d'*32,'revision':1,'model':'fake','review_fingerprint':'e'*64,'suite':proposal()}
    path.write_text(json.dumps(packet),encoding='utf-8')
    contract={**packet,'report':str(path),'fingerprint':hashlib.sha256(path.read_bytes()).hexdigest()}
    browser={'passed':True,'results':[{'id':'counter_actions','criteria':[1,2],'passed':True}]}
    commands=[];cleanup=[]
    monkeypatch.setattr(module,'docker',lambda *args:'sha256:'+'b'*64 if args[0]=='image' else 'network')
    monkeypatch.setattr(module,'cleanup_browser',lambda *args:cleanup.append(args))
    def execute(args,**_):
        commands.append(args)
        if '--detach' not in args:(directory/'results/browser.json').write_text(json.dumps(browser),encoding='utf-8')
        return {'command':args,'exit_code':0,'stopped':None,'output':''}
    monkeypatch.setattr(module,'bounded_command',execute)
    return root,directory,contract,browser,commands,cleanup


def test_requirements_contract_is_never_mounted_in_the_application_container(setup):
    root,directory,contract,_,commands,cleanup=setup
    report=module.run_acceptance_browser(root,directory,'c'*32,contract,'sha256:'+'d'*64)
    assert report['passed'] and len(cleanup)==1
    assert report['uncovered'][0]['criterion']==3
    assert report['contract_unchanged'] and report['harness_unchanged']
    assert any('target=/source,readonly' in item for item in commands[0])
    assert not any('contract.json' in item or 'browser-protocol' in item for item in commands[0])
    assert any('target=/trusted/contract.json,readonly' in item for item in commands[1])
    assert not any('target=/source' in item for item in commands[1])


@pytest.mark.parametrize('change',[
    lambda r:r['browser']['results'].pop(),
    lambda r:r['browser']['results'][0].update(passed=False),
    lambda r:r['browser']['results'][0].update(criteria=[3]),
    lambda r:r['browser']['results'][0].update(id='invented'),
    lambda r:r.update(source_unchanged=False),
    lambda r:r.update(contract_unchanged=False),
    lambda r:r.update(harness_unchanged=False),
    lambda r:r.update(job_id='f'*32),
    lambda r:r.update(cleanup_errors=['cleanup failed']),
    lambda r:r.update(error='Execution failed'),
    lambda r:r['execution'].update(exit_code=1),
])
def test_incomplete_stale_failed_or_wrong_contract_evidence_cannot_pass(setup,change):
    root,directory,contract,_,_,_=setup
    report=module.run_acceptance_browser(root,directory,'c'*32,contract,'sha256:'+'d'*64)
    assert module.passed_report(report,contract)
    change(report);assert not module.passed_report(report,contract)


def test_contract_change_during_browser_execution_invalidates_results_and_cleans_resources(setup,monkeypatch):
    root,directory,contract,_,_,cleanup=setup
    execute=module.bounded_command
    def tamper(args,**kwargs):
        result=execute(args,**kwargs)
        if '--detach' not in args:
            from pathlib import Path
            Path(contract['report']).write_text('{}',encoding='utf-8')
        return result
    monkeypatch.setattr(module,'bounded_command',tamper)
    report=module.run_acceptance_browser(root,directory,'c'*32,contract,'sha256:'+'d'*64)
    assert not report['passed'] and not report['contract_unchanged'] and len(cleanup)==1


def test_setup_failure_records_owned_resources_and_cleans_them(setup,monkeypatch):
    root,directory,contract,_,_,cleanup=setup
    def unavailable(*_):
        assert json.loads((directory/'report.json').read_text())['phase']=='started'
        raise RuntimeError('Docker unavailable')
    monkeypatch.setattr(module,'docker',unavailable)
    report=module.run_acceptance_browser(root,directory,'c'*32,contract,'sha256:'+'d'*64)
    assert not report['passed'] and 'Docker unavailable' in report['error'] and cleanup
