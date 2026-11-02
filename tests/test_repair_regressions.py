import importlib.util
import json
from pathlib import Path

import pytest

from forge.workspace import source_fingerprint


spec=importlib.util.spec_from_file_location('repair_evaluation',Path(__file__).resolve().parents[1]/'scripts/evaluate_repair_regressions.py')
evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)


@pytest.mark.parametrize('failure',[None,'browser_failure','stale_browser','wrong_image','changed_source'])
def test_successful_build_cannot_mask_failed_or_stale_browser_evidence(tmp_path,monkeypatch,failure):
    root=tmp_path/'source';root.mkdir();(root/'page.txt').write_text('source')
    image='sha256:'+'a'*64;fingerprint=source_fingerprint(root)
    build={'passed':True,'report':'build.json','image':image,'source_fingerprint':fingerprint,
        'cleanup_errors':[],'coverage':{'application_behavior':'NOT_TESTED'},'checks':{'passed':True,
            'results':[{'name':'typecheck','exit_code':0},{'name':'production_build','exit_code':0}]}}
    browser={'passed':failure!='browser_failure','report':'browser.json','app_image':image,
        'source_fingerprint':fingerprint,'harness_fingerprint':'b'*64,'scope':'Frozen fixture',
        'cleanup_errors':[],'browser':{'results':[{'name':'uppercases_name','passed':failure!='browser_failure'}]}}
    if failure=='stale_browser':browser['source_fingerprint']='c'*64
    if failure=='wrong_image':browser['app_image']='sha256:'+'d'*64
    monkeypatch.setattr(evaluation,'run_source_checks',lambda *args:build)
    def browser_check(*args):
        if failure=='changed_source':(root/'page.txt').write_text('changed during checks')
        return browser
    monkeypatch.setattr(evaluation,'run_fixture_browser',browser_check)
    result=evaluation.verification_runner(tmp_path,'e'*32,'formatter')(root)
    assert result['passed'] is (failure is None)
    assert result['checks']['passed'] is result['passed']
    assert all(row['exit_code']==0 for row in result['checks']['results'][:2])
    assert json.loads(Path(result['report']).read_text())['passed']==result['passed']
