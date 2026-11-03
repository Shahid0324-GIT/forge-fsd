import json

import pytest

from forge.check_context import observed_context
from forge.tasks import CheckEvidence,Observation


def evidence(path):
    return Observation(revision=1,fingerprint='a'*64,checks=[CheckEvidence(check='isolated_build',exit_code=1,
        fingerprint='a'*64,report=str(path),summary='Cached client-boundary warning from an old summarizer')])


def test_actual_browser_failure_replaces_cached_passing_build_advisory(tmp_path):
    path=tmp_path/'report.json';path.write_text(json.dumps({'source_fingerprint':'a'*64,'checks':{
        'results':[{'name':'typecheck','exit_code':0,'output':'passed'},
            {'name':'production_build','exit_code':0,'output':'passed'},
            {'name':'browser_acceptance','exit_code':1,'output':'Expected visible count was missing'}],
        'source_diagnostics':[{'file':'app/page.tsx','line':1,'column':1,'code':'CLIENT_HINT','message':'Obsolete advisory'}]}}),encoding='utf-8')
    original=evidence(path);context=observed_context(original,tmp_path)
    assert 'Expected visible count was missing' in context['checks'][0]['summary']
    assert 'client-boundary' not in context['checks'][0]['summary'] and 'Obsolete advisory' not in context['checks'][0]['summary']
    assert original.checks[0].summary.startswith('Cached')


def test_report_for_another_source_cannot_be_used_as_current_context(tmp_path):
    path=tmp_path/'report.json';path.write_text(json.dumps({'source_fingerprint':'b'*64}),encoding='utf-8')
    with pytest.raises(ValueError,match='fingerprint'):observed_context(evidence(path),tmp_path)


def test_context_reader_does_not_follow_reports_outside_its_artifact_root(tmp_path):
    root=tmp_path/'artifacts';root.mkdir();path=tmp_path/'outside.json'
    path.write_text('not a trusted report',encoding='utf-8')
    context=observed_context(evidence(path),root)
    assert context['checks'][0]['summary'].startswith('Cached')
