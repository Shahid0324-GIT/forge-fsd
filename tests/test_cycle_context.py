from types import SimpleNamespace

from forge.cycle_context import rejected_state_context,failure_obligations
from forge.tasks import Observation,CheckEvidence


def observation(fp,*,revision=1,error='',summary='',check='isolated_build',exit_code=1):
    return Observation(revision=revision,fingerprint=fp,error=error,checks=[] if not summary else [
        CheckEvidence(check=check,exit_code=exit_code,fingerprint=fp,report='not-present.json',summary=summary)])


def test_cycle_uses_actual_same_revision_failed_observation_and_marks_it_historical(tmp_path):
    fp='a'*64
    state=SimpleNamespace(revision=1,observations=[observation(fp,summary='Compiler failure'),
        observation('b'*64,error=f'ValueError: Repair cycle rejected: this would restore an already failed workspace {fp}. No source was written.')])
    result=rejected_state_context(state,tmp_path)
    assert result['rejected_fingerprint']==fp
    assert result['historical_failure']['fingerprint']==fp
    assert 'NOT current' in result['scope']


def test_old_revision_success_and_unverified_error_hash_cannot_supply_cycle_evidence(tmp_path):
    fp='a'*64
    for prior in [observation(fp,revision=1,summary='old'),observation(fp,revision=2,summary='ok',exit_code=0),
                  observation(fp,revision=2,summary='not a build',check='other')]:
        state=SimpleNamespace(revision=2,observations=[prior,observation('b'*64,revision=2,
            error=f'Repair cycle rejected: this would restore an already failed workspace {fp}.')])
        assert rejected_state_context(state,tmp_path) is None


def test_unrelated_tool_failure_does_not_replay_old_cycle(tmp_path):
    state=SimpleNamespace(revision=1,observations=[observation('b'*64,error='A different tool failed')])
    assert rejected_state_context(state,tmp_path) is None


def test_current_and_rejected_failures_are_distinct_deduplicated_and_snapshot_scoped():
    locations=[{'file':'app/page.tsx','code':'CLIENT_HOOK_WITHOUT_DIRECTIVE','message':'Missing client boundary'}]
    cycle={'historical_failure':{'checks':[{'check':'isolated_build','exit_code':1,'summary':
        "app/page.tsx(4,1): error TS2307: Cannot find module './helper'.\napp/page.tsx(4,1): error TS2307: Cannot find module './helper'.\nunknown.ts(1,1): error TS1234: Unknown file"}]}}
    rows=failure_obligations(locations,cycle,{'app/page.tsx':{}})
    assert len(rows)==2
    assert rows[0]['source_state']=='current'
    assert rows[1]['source_state']=='rejected_candidate' and rows[1]['code']=='TS2307'
    assert [row['id'] for row in rows]==['failure_1','failure_2']
