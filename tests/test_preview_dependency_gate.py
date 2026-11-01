import json

import pytest

from forge.preview import check_preview_gate
from test_preview import preview_fixture


def test_preview_rejects_stale_python_dependency_audit(tmp_path):
    root,path,record=preview_fixture(tmp_path)
    report=json.loads(path.read_text());report['checks']['pip_audit']['lock_sha256']='0'*64
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError,match='dependencies changed'):
        check_preview_gate(record,root)
