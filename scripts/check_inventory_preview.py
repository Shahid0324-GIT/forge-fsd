"""Reproduce selected HTTP/concurrency checks against the approved disposable preview."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from forge.persistence import JobStore
from forge.workspace import source_fingerprint

JOB = '1ff5378844a0433c9819ac0489199b54'
PROJECT = Path(__file__).resolve().parents[1]


def main():
    job = JobStore(PROJECT / 'artifacts/jobs.sqlite3').read(JOB)
    assert job['status'] == 'PREVIEW_RUNNING'
    preview = next(e['payload'] for e in reversed(job['events']) if e['status'] == 'PREVIEW_RUNNING')
    fingerprint = source_fingerprint(PROJECT / 'workspace' / JOB)
    assert preview['source_fingerprint'] == fingerprint
    cases = []

    def request(path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        try:
            response = urlopen(Request(preview['url'] + path, data=data, headers={'Content-Type': 'application/json'}), timeout=15)
        except HTTPError as error:
            response = error
        return response.status, json.load(response)

    def check(name, path, expected, body=None, raw=None):
        status, result = request(path, body, raw)
        cases.append(dict(name=name, status=status, expected=expected, response=result))
        assert status == expected, cases[-1]
        return result

    product = check('create concurrency fixture', '/api/products', 201, {'name': 'Concurrency proof', 'unitPrice': 3})
    pid = product['id']
    assert product['stock'] == 0
    check('stock in', '/api/movements', 201, {'productId': pid, 'quantity': 10})
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: request('/api/movements', {'productId': pid, 'quantity': -7}), range(2)))
    assert sorted(status for status, _ in outcomes) == [201, 400], outcomes
    cases.append(dict(name='two concurrent stock-outs of seven from ten', outcomes=outcomes, passed=True))
    for name, body in [('zero', {'productId': pid, 'quantity': 0}),
                       ('fraction', {'productId': pid, 'quantity': 1.5}),
                       ('string quantity', {'productId': pid, 'quantity': '1'}),
                       ('extra field', {'productId': pid, 'quantity': 1, 'admin': True})]:
        check(name, '/api/movements', 400, body)
    check('missing product', '/api/movements', 404, {'productId': 2147483647, 'quantity': 1})
    for path in ['/api/products', '/api/movements']:
        for name, raw in [('null', b'null'), ('array', b'[]'), ('malformed', b'{')]:
            check(path + ' ' + name, path, 400, raw=raw)
    check('blank product', '/api/products', 400, {'name': '  ', 'unitPrice': 1})
    check('negative price', '/api/products', 400, {'name': 'Invalid', 'unitPrice': -1})
    products = check('read final products', '/api/products', 200)
    concurrent = next(p for p in products if p['id'] == pid)
    assert concurrent['stock'] == 3 and concurrent['inventoryValue'] == 9, concurrent
    browser_product = next(p for p in products if p['name'] == 'USB-C câble')
    assert browser_product['stock'] == 7 and browser_product['inventoryValue'] == 17.5, browser_product

    container = preview['preview']['container']
    info = json.loads(subprocess.check_output(['docker', 'inspect', container], text=True))[0]
    assert info['Config']['Labels']['forge.job'] == JOB
    assert info['Config']['Labels']['forge.role'] == 'preview'
    sql = """const {DatabaseSync}=require('node:sqlite');
const db=new DatabaseSync(process.env.SQLITE_PATH,{readOnly:true});
console.log(JSON.stringify({movement:db.prepare('SELECT COUNT(*) AS count,SUM(quantity) AS stock FROM movements WHERE product_id=?').get(Number(process.argv[1])),foreignKeys:db.prepare('PRAGMA foreign_key_check').all(),integrity:db.prepare('PRAGMA quick_check').all()}));"""
    physical = json.loads(subprocess.check_output(['docker', 'exec', '--user', '1000:1000', container, 'node', '-e', sql, str(pid)], text=True))
    assert physical['movement'] == {'count': 2, 'stock': 3} and physical['foreignKeys'] == [], physical
    assert physical['integrity'] == [{'quick_check': 'ok'}], physical
    report = dict(job_id=JOB, source_fingerprint=fingerprint, preview_url=preview['url'], cases=cases, physical_database=physical, passed=True)
    path = PROJECT / 'artifacts/general-app-evaluation/inventory-preview-api.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': True, 'cases': len(cases), 'physical_database': physical, 'report': str(path)}))


if __name__ == '__main__':
    main()
