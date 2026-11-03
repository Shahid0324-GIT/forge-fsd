"""Route unambiguous current compiler failures to their existing source owner."""
from forge.check_context import observed_context
from forge.source_agent import diagnostic_context
from forge.workspace import safe_path,source_fingerprint


def compiler_repair_owner(state,root,owners,artifact_root):
    fingerprint=source_fingerprint(root)
    failed=next((o for o in reversed(state.observations) if o.revision==state.revision
        and o.fingerprint==fingerprint and any(c.check=='isolated_build' and c.exit_code!=0 for c in o.checks)),None)
    if failed is None:return None
    source={path:{'content':safe_path(root,path).read_text(encoding='utf-8')}
        for path in owners if safe_path(root,path).is_file()}
    locations=diagnostic_context(observed_context(failed,artifact_root),source)
    roles={owners[row['file']] for row in locations if row['file'] in owners}
    # Ambiguous failures and errors in this owner's files remain agent decisions.
    if len(roles)==1 and state.task.owner not in roles:return next(iter(roles))
    return None
