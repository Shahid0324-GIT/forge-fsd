from pathlib import Path
from typing import Literal

from pydantic import Field

from forge.schemas import Boundary
from forge.workspace import OWNERS, safe_path


class ActionProposal(Boundary):
    action: Literal['continue', 'read_file', 'write_file', 'run_command', 'mark_ready']
    target: str = Field(max_length=500)
    reason: str = Field(max_length=1000)


def authorize_proposal(proposal: ActionProposal, root: Path, owners=None):
    if proposal.action == 'continue':
        return True, 'Continue without a tool operation'
    if proposal.action in {'run_command', 'mark_ready'}:
        return False, 'Raw model commands and model-declared readiness are forbidden'
    try:
        path = safe_path(root, proposal.target)
    except ValueError:
        return False, 'Path is outside the permitted workspace boundary'
    owned = set().union(*(owners if owners is not None else OWNERS).values())
    if proposal.target not in owned:
        return False, 'Target is not a builder-owned source file'
    if proposal.action == 'read_file' and not path.is_file():
        return False, 'Source file does not exist'
    return True, 'Within the source-file capability boundary'
