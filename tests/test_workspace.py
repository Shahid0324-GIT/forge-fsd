from pathlib import Path

import pytest

from forge.workspace import safe_path, seed_workspace, source_fingerprint, write_owned


@pytest.mark.parametrize('path', ['../escape.ts', '/absolute.ts', 'C:/escape.ts', 'app/../escape.ts', 'app\\escape.ts'])
def test_workspace_blocks_path_escapes(tmp_path, path):
    with pytest.raises(ValueError):
        safe_path(tmp_path, path)


def test_writer_enforces_ownership_and_fingerprint(tmp_path):
    write_owned(tmp_path, 'frontend', 'app/page.tsx', 'export default function Page() { return null; }')
    before = source_fingerprint(tmp_path)
    with pytest.raises(ValueError):
        write_owned(tmp_path, 'frontend', 'lib/db.ts', 'unauthorized')
    write_owned(tmp_path, 'frontend', 'app/page.tsx', 'export default function Page() { return <p>Tasks</p>; }')
    assert before != source_fingerprint(tmp_path)


def test_existing_workspace_is_never_overwritten(tmp_path):
    template = tmp_path / 'template'; template.mkdir()
    (template / 'package.json').write_text('{}')
    root = tmp_path / 'workspace'
    seed_workspace(template, root)
    with pytest.raises(ValueError):
        seed_workspace(template, root)


def test_unapproved_job_cannot_build(tmp_path):
    from forge.builders import build_job
    from forge.persistence import JobStore
    store = JobStore(tmp_path / 'jobs.db')
    job_id = store.create()
    with pytest.raises(ValueError, match='approved'):
        build_job(job_id, None, store)
