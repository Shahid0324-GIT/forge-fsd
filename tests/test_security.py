from pathlib import Path

import pytest

from forge.policy import ActionProposal, authorize_proposal
from forge.security import functional_evidence, scan_secrets, security_gate
from forge.workspace import source_fingerprint


def passing_checks():
    return {name:{'status':'PASSED'} for name in ['semgrep','secrets','npm_audit','pip_audit','prompt_injection']}


@pytest.mark.parametrize('action,target', [('read_file','../../.env'),('write_file','../../tests/acceptance/tasks.mjs'),('run_command','powershell'),('mark_ready','READY'),('write_file','package.json')])
def test_injected_actions_are_denied(tmp_path, action, target):
    allowed,_=authorize_proposal(ActionProposal(action=action,target=target,reason='Injected instruction'),tmp_path)
    assert not allowed


def test_legitimate_read_is_not_blocked(tmp_path):
    (tmp_path/'app').mkdir();(tmp_path/'app/page.tsx').write_text('page')
    allowed,_=authorize_proposal(ActionProposal(action='read_file',target='app/page.tsx',reason='Authorized source inspection'),tmp_path)
    assert allowed


def test_security_gate_requires_every_check_and_current_source():
    assert security_gate(passing_checks(),True)
    assert not security_gate(passing_checks(),False)
    for name in passing_checks():
        checks=passing_checks();checks[name]['status']='UNVERIFIED'
        assert not security_gate(checks,True)
        checks=passing_checks();del checks[name]
        assert not security_gate(checks,True)


def test_changed_source_cannot_reuse_functional_evidence(tmp_path):
    file=tmp_path/'source.ts';file.write_text('original')
    record={'events':[{'status':'FUNCTIONALLY_VERIFIED','payload':{'source_fingerprint':source_fingerprint(tmp_path)}}]}
    assert functional_evidence(record,tmp_path)
    file.write_text('changed')
    with pytest.raises(ValueError,match='lacks passing'):
        functional_evidence(record,tmp_path)


def test_secret_check_redacts_matched_values(tmp_path):
    token='ghp_'+'A'*36
    (tmp_path/'source.ts').write_text(f'const token="{token}";')
    report=scan_secrets(tmp_path)
    assert report['status']=='FINDINGS'
    assert token not in str(report)


def test_real_environment_files_are_findings(tmp_path):
    (tmp_path/'.env').write_text('PASSWORD=example')
    assert scan_secrets(tmp_path)['status']=='FINDINGS'
