"""Keep rejected-state evidence distinct from current-source diagnostics."""
import re

from forge.check_context import observed_context


def rejected_state_context(state,artifact_root):
    history=[o for o in state.observations if o.revision==state.revision]
    if not history:return None
    match=re.search(r'Repair cycle rejected: this would restore an already failed workspace ([a-f0-9]{64})\.',history[-1].error)
    if not match:return None
    fingerprint=match[1]
    failed=next((o for o in reversed(history) if o.fingerprint==fingerprint
        and any(c.check=='isolated_build' and c.exit_code!=0 for c in o.checks)),None)
    if failed is None:return None
    return {'rejected_fingerprint':fingerprint,'historical_failure':observed_context(failed,artifact_root),
        'scope':'Historical evidence for a rejected candidate, NOT current-source evidence. Fix current causes without reintroducing these failures. Do not restore this snapshot.'}


def failure_obligations(locations,cycle,source):
    """Stable, bounded file-specific planning obligations, not proof of correction."""
    rows=[];seen=set()
    for row in locations:
        key=(row['file'],row['code'],row['message'])
        if key not in seen:
            rows.append({'file':key[0],'code':key[1],'message':key[2],'source_state':'current'});seen.add(key)
    if cycle:
        for check in cycle['historical_failure']['checks']:
            if check['check']!='isolated_build' or check['exit_code']==0:continue
            for match in re.finditer(r'([^\s:()]+\.(?:tsx?|jsx?))\((\d+),(\d+)\): (?:error )?([A-Z_]+\d*): ([^\n]+)',check['summary']):
                key=(match[1],match[4],match[5])
                if key[0] in source and key not in seen:
                    rows.append({'file':key[0],'code':key[1],'message':key[2],'source_state':'rejected_candidate'});seen.add(key)
    return [{**row,'id':f'failure_{i+1}'} for i,row in enumerate(rows[:12])]
