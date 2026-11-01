"""Record selected HTTP checks against the owned, running converter preview."""
import argparse
import json
import math
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from forge.persistence import JobStore
from forge.workspace import source_fingerprint

PROJECT = Path(__file__).resolve().parents[1]
JOB = '4b3fd81eb76f4be19780ef9a1b98d156'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', choices=['initial', 'final'], default='final')
    args = parser.parse_args()
    record = JobStore(PROJECT / 'artifacts/jobs.sqlite3').read(JOB)
    assert record['status'] == 'PREVIEW_RUNNING'
    preview = next(e['payload'] for e in reversed(record['events']) if e['status'] == 'PREVIEW_RUNNING')
    assert re.fullmatch(r'http://127\.0\.0\.1:\d+', preview['url'])
    fingerprint = source_fingerprint(PROJECT / 'workspace' / JOB)
    assert fingerprint == preview['source_fingerprint']
    cases = []

    def check(name, body, expected_status, expected=None, raw=None):
        data = raw if raw is not None else json.dumps(body).encode()
        try:
            response = urlopen(Request(preview['url'] + '/api/convert', data=data,
                                       headers={'Content-Type': 'application/json'}), timeout=10)
        except HTTPError as error:
            response = error
        actual = json.load(response)
        row = {'name': name, 'status': response.status, 'expected_status': expected_status, 'response': actual}
        cases.append(row)
        assert response.status == expected_status, row
        if expected:
            assert type(actual['result']) in {int, float} and math.isfinite(actual['result']), row
            assert math.isclose(actual['result'], expected['result'], rel_tol=1e-12, abs_tol=1e-10), row
            assert actual['unit'] == expected['unit'], row

    for name, body, expected in [
        ('zero Celsius', {'value': 0, 'from': 'C'}, {'result': 32, 'unit': 'F'}),
        ('boiling Fahrenheit', {'value': 212, 'from': 'F'}, {'result': 100, 'unit': 'C'}),
        ('negative Celsius', {'value': -40, 'from': 'C'}, {'result': -40, 'unit': 'F'}),
        ('decimal Celsius', {'value': 36.5, 'from': 'C'}, {'result': 97.7, 'unit': 'F'}),
        ('decimal Fahrenheit', {'value': 99.5, 'from': 'F'}, {'result': 37.5, 'unit': 'C'}),
    ]:
        check(name, body, 200, expected)
    for name, body in [
        ('invalid source unit', {'value': 10, 'from': 'K'}),
        ('missing source unit', {'value': 10}),
        ('missing value', {'from': 'C'}),
        ('string value', {'value': '10', 'from': 'C'}),
        ('boolean value', {'value': True, 'from': 'C'}),
        ('array body', []), ('string body', 'not an object'), ('null body', None),
    ]:
        check(name, body, 400)
    check('malformed JSON', None, 400, raw=b'{')
    check('nonfinite JSON number', None, 400, raw=b'{"value":1e309,"from":"C"}')
    report = {'job_id': JOB, 'source_fingerprint': fingerprint, 'preview_url': preview['url'], 'passed': True,
              'scope': 'Selected direct HTTP checks; does not establish browser behavior or all numerical edge cases.', 'cases': cases}
    path = PROJECT / f'artifacts/general-app-evaluation/converter-preview-api-{args.label}.json'
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'cases': len(cases), 'report': str(path)}))


if __name__ == '__main__':
    main()
