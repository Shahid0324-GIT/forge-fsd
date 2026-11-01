"""Run the fixed browser profile and its stale-unit calibration without a model."""
import argparse
import json
from pathlib import Path
from uuid import uuid4

from forge.browser_testing import run_browser_checks
from forge.workspace import seed_workspace

PROJECT=Path(__file__).resolve().parents[1]


def prepare(root,variant):
    seed_workspace(PROJECT/'templates/task-app',root,generic=True)
    for relative in ['app/page.tsx','app/api/convert/route.ts']:
        text=(PROJECT/'tests/fixtures/temperature-converter'/relative).read_text(encoding='utf-8')
        if variant=='stale-unit' and relative=='app/page.tsx':
            old="setFrom(e.target.value as 'C' | 'F');\n    setResult(null);"
            assert text.count(old)==1,'Calibration target changed; review the fixture mutation'
            text=text.replace(old,"setFrom(e.target.value as 'C' | 'F');\n    // Deliberately retain the old number while its unit label changes.")
        target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text,encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant',choices=['correct','stale-unit','both'],default='both')
    args=parser.parse_args()
    directory=PROJECT/'artifacts/browser-calibration'/uuid4().hex
    variants=['correct','stale-unit'] if args.variant=='both' else [args.variant]
    rows=[]
    for variant in variants:
        root=directory/variant/'source';prepare(root,variant)
        report,path=run_browser_checks(root,directory/variant/'evidence',uuid4().hex)
        failed={r['name'] for r in report.get('browser',{}).get('results',[]) if not r['passed']}
        expected=report['passed'] if variant=='correct' else (
            not report['passed'] and failed=={'source_unit_does_not_relabel_result'}
            and len(report.get('browser',{}).get('results',[]))==8)
        rows.append({'variant':variant,'passed':report['passed'],'expected_outcome_observed':expected,'report':str(path),'failed_cases':sorted(failed)})
        print(json.dumps(rows[-1]),flush=True)
    path=directory/'calibration.json';path.write_text(json.dumps(rows,indent=2),encoding='utf-8')
    print('Calibration evidence: '+str(path),flush=True)
    return int(not all(row['expected_outcome_observed'] for row in rows))


if __name__=='__main__':raise SystemExit(main())
