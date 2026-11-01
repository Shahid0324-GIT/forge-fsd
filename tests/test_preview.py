import json
import hashlib

import pytest

from forge.preview import check_preview_gate, cleanup, start_preview
from forge.workspace import source_fingerprint
from test_security import passing_checks


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
