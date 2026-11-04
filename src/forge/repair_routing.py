"""Route unambiguous current compiler/build failures to their existing owner."""
import re
from pathlib import PurePosixPath
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
    evidence=observed_context(failed,artifact_root)
    locations=diagnostic_context(evidence,source)
    roles={owners[row['file']] for row in locations if row['file'] in owners}
    # Next build identifies failed route modules without TypeScript coordinates.
    # Match only explicit failed-collection receipts against existing app entries;
    # a database keyword or an arbitrary stack frame is not ownership evidence.
    routes=set(re.findall(r'Failed to collect (?:configuration|page data) for (/[-a-zA-Z0-9_./%\[\]]*)',
        '\n'.join(check['summary'] for check in evidence['checks'])))
    for path in source:
        parts=PurePosixPath(path).parts
        if len(parts)<2 or parts[0]!='app' or parts[-1] not in {'page.ts','page.tsx','route.ts','route.tsx'}:continue
        segments=[part for part in parts[1:-1] if not (part.startswith('(') and part.endswith(')'))]
        if '/'+('/'.join(segments)) in routes:roles.add(owners[path])
    # Ambiguous failures and errors in this owner's files remain agent decisions.
    if len(roles)==1 and state.task.owner not in roles:return next(iter(roles))
    return None
