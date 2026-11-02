import json

import pytest

import forge.repair_fixture_browser as module


def report():
    return {'fixture':'formatter','source_unchanged':True,'harness_unchanged':True,
        'harness_fingerprint':module.harness_fingerprint(),'cleanup_errors':[],
        'execution':{'exit_code':0,'stopped':None},'browser':{'fixture':'formatter','passed':True,
            'results':[{'name':name,'passed':True} for name in sorted(module.CASES['formatter'])]}}


@pytest.mark.parametrize('change',[
    lambda r:r['browser']['results'].pop(),
    lambda r:r['browser']['results'][0].update(passed=False),
    lambda r:r['browser'].update(fixture='counter'),
    lambda r:r.update(harness_unchanged=False),
    lambda r:r.update(source_unchanged=False),
    lambda r:r['execution'].update(exit_code=1),
    lambda r:r.update(cleanup_errors=['cleanup failed']),
])
def test_fixture_evidence_must_be_complete_current_and_successful(change):
    data=report();assert module.passed_report(data)
    change(data);assert not module.passed_report(data)


def test_browser_assertions_are_not_mounted_with_app_source_and_cleanup_always_runs(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    monkeypatch.setattr(module,'harness_fingerprint',lambda:'a'*64)
    root=tmp_path/'workspace';root.mkdir();(root/'package.json').write_text('{}')
    cleanup=[];commands=[]
    monkeypatch.setattr(module,'docker',lambda *args:'sha256:'+'b'*64 if args[0]=='image' else 'network')
    monkeypatch.setattr(module,'cleanup_browser',lambda *args:cleanup.append(args))
    output=tmp_path/'artifacts/check/results'
    def execute(args,**_):
        commands.append(args)
        if '--detach' not in args:
            (output/'browser.json').write_text(json.dumps(report()['browser']),encoding='utf-8')
        return {'command':args,'exit_code':0,'stopped':None,'output':''}
    monkeypatch.setattr(module,'bounded_command',execute)
    result=module.run_fixture_browser(root,tmp_path/'artifacts/check','c'*32,'formatter','sha256:'+'d'*64)
    assert result['passed'] and len(cleanup)==1 and len(commands)==2
    assert any('target=/source,readonly' in arg for arg in commands[0])
    assert not any('tests/repair' in arg or 'tests\\repair' in arg for arg in commands[0])
    assert not any('target=/source' in arg for arg in commands[1])
    assert any('target=/trusted/browser.mjs,readonly' in arg for arg in commands[1])


def test_startup_exception_cannot_leak_owned_resources_or_pass(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    monkeypatch.setattr(module,'harness_fingerprint',lambda:'a'*64)
    root=tmp_path/'workspace';root.mkdir();(root/'package.json').write_text('{}')
    cleanup=[]
    monkeypatch.setattr(module,'cleanup_browser',lambda *args:cleanup.append(args))
    def fail(*_):
        started=json.loads((tmp_path/'artifacts/check/report.json').read_text())
        assert started['phase']=='started' and started['passed'] is False
        assert started['job_id']=='c'*32 and set(started['resources'])=={'app','browser','network'}
        raise RuntimeError('Docker unavailable')
    monkeypatch.setattr(module,'docker',fail)
    result=module.run_fixture_browser(root,tmp_path/'artifacts/check','c'*32,'formatter','sha256:'+'d'*64)
    assert not result['passed'] and cleanup and 'Docker unavailable' in result['error']
