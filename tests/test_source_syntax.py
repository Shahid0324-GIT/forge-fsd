import json
from uuid import uuid4

import pytest

from forge.source_syntax import run_source_syntax
from forge.tasks import TaskBlockedError


@pytest.mark.parametrize('file,source,passed',[
    ('app/page.tsx','export default function Page(){return <main>日本語 café</main>}',True),
    ('lib/service.ts','export async function load():Promise<number>{return 7}',True),
    ('app/page.tsx','export default function Page(){return <main>Broken</div>}',False),
    ('lib/service.ts','export const value: = 7',False),
])
def test_real_typescript_parser_reports_syntax_without_claiming_types(tmp_path,file,source,passed):
    path=tmp_path/file;path.parent.mkdir(parents=True);path.write_text(source,encoding='utf-8')
    result=run_source_syntax(tmp_path,file,tmp_path/'reports',uuid4().hex)
    assert result['passed'] is passed
    assert bool(result['diagnostics']) is not passed
    assert 'behavior remain unverified' in result['scope']
    assert json.loads(__import__('pathlib').Path(result['report']).read_text())['passed'] is passed


def test_generated_code_and_its_configuration_are_never_executed(tmp_path):
    sentinel=tmp_path/'executed'
    source='import {writeFileSync} from "node:fs"; writeFileSync('+json.dumps(str(sentinel))+',"unsafe"); throw new Error("must not execute");'
    (tmp_path/'module.ts').write_text(source,encoding='utf-8')
    (tmp_path/'tsconfig.json').write_text('{"compilerOptions":{"plugins":[{"name":"does-not-exist"}]}}')
    assert run_source_syntax(tmp_path,'module.ts',tmp_path/'reports',uuid4().hex)['passed']
    assert not sentinel.exists()


def test_parser_environment_failure_is_not_an_app_defect(tmp_path,monkeypatch):
    import forge.source_syntax as module
    (tmp_path/'module.ts').write_text('export const n=1')
    monkeypatch.setattr(module,'TYPESCRIPT',tmp_path/'missing-parser.js')
    with pytest.raises(TaskBlockedError,match='unavailable'):
        run_source_syntax(tmp_path,'module.ts',tmp_path/'reports',uuid4().hex)


def test_syntax_evidence_binds_actual_bytes_including_windows_line_endings(tmp_path):
    import hashlib
    raw=b'export const first=1;\r\nexport const second=2;\r\n'
    (tmp_path/'module.ts').write_bytes(raw)
    report=run_source_syntax(tmp_path,'module.ts',tmp_path/'reports',uuid4().hex)
    assert report['passed'] and report['source_sha256']==hashlib.sha256(raw).hexdigest()
