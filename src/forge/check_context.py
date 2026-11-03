"""Reconstruct model debugging input from controller-owned execution reports."""
import json
from pathlib import Path


def summarize_checks(rows,diagnostics=(),error=None):
    failed=[row for row in rows if row.get('exit_code')!=0 or row.get('stopped')]
    build_failed=any(row.get('name') in {'typecheck','production_build'} for row in failed)
    hints=[f"{row['file']}({row['line']},{row['column']}): {row['code']}: {row['message']}"
        for row in diagnostics if build_failed]
    actual=[f"{row.get('name')} (exit {row.get('exit_code')}): {row.get('output','')}" for row in (failed or rows)]
    return '\n'.join([*hints,*actual,*([str(error)] if error else [])])[:2000]


def observed_context(observation,artifact_root):
    packet=observation.model_dump()
    for check in packet['checks']:
        if check['check']!='isolated_build':continue
        path=Path(check['report']).resolve()
        if not path.is_relative_to(Path(artifact_root).resolve()) or not path.is_file() or path.stat().st_size>1_000_000:continue
        report=json.loads(path.read_text(encoding='utf-8'))
        if report.get('source_fingerprint')!=observation.fingerprint:raise ValueError('Verification report fingerprint does not match its observation')
        checks=report.get('checks',{});rows=checks.get('results',[])
        if rows:
            check['summary']=summarize_checks(rows,checks.get('source_diagnostics',[]),
                report.get('error') or checks.get('error') or report.get('cleanup_errors'))
    return packet
