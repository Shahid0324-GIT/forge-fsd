import pytest

from forge.repair_routing import compiler_repair_owner
from forge.tasks import CheckEvidence,Observation
from forge.workspace import source_fingerprint
from test_workspace_tools import tools


@pytest.mark.parametrize('summary,expected',[
    ('lib/types.ts(1,1): error TS1234: Backend failure','backend'),
    ('app/page.tsx(1,1): error TS1234: Frontend failure',None),
    ('app/page.tsx(1,1): error TS1234: Frontend failure\nlib/types.ts(1,1): error TS1234: Backend failure',None),
    ('Browser assertion failed on page',None)])
def test_only_unambiguous_current_other_owner_diagnostics_route(tools,summary,expected):
    for path in ['app/page.tsx','lib/types.ts']:
        item=tools.root/path;item.parent.mkdir(parents=True,exist_ok=True);item.write_text('export const value=1;\n')
    fp=source_fingerprint(tools.root)
    state=tools.ledger.observe(tools.state,Observation(revision=tools.state.revision,fingerprint=fp,
        checks=[CheckEvidence(check='isolated_build',exit_code=1,fingerprint=fp,report='missing.json',summary=summary)]))
    assert compiler_repair_owner(state,tools.root,tools.owners,tools.ledger.store.path.parent)==expected
    (tools.root/'app/page.tsx').write_text('export const value=2;\n')
    assert compiler_repair_owner(state,tools.root,tools.owners,tools.ledger.store.path.parent) is None


def test_old_revision_diagnostics_cannot_reassign_work(tools):
    item=tools.root/'lib/types.ts';item.parent.mkdir(parents=True,exist_ok=True);item.write_text('export const value=1;\n')
    fp=source_fingerprint(tools.root)
    state=tools.ledger.observe(tools.state,Observation(revision=tools.state.revision,fingerprint=fp,
        checks=[CheckEvidence(check='isolated_build',exit_code=1,fingerprint=fp,report='missing.json',summary='lib/types.ts(1,1): error TS1234: Old failure')]))
    state=tools.ledger.revise(state,state.task)
    assert compiler_repair_owner(state,tools.root,tools.owners,tools.ledger.store.path.parent) is None
