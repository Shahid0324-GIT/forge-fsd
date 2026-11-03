"""Bounded relative-module facts from the same source snapshot as diagnostics."""
import posixpath
import re


_EXTENSIONS=('.tsx','.ts','.jsx','.js')


def relative_import_reference(importer,message,source):
    match=re.search(r"Cannot find module ['\"]([^'\"]+)['\"]",message)
    if not match or not match[1].startswith(('./','../')):return None
    requested=match[1]
    base=posixpath.normpath(posixpath.join(posixpath.dirname(importer),requested))
    if base.startswith('../') or base=='..':
        resolved=[]
    else:
        names=[base,*[base+ext for ext in _EXTENSIONS],*[base+'/index'+ext for ext in _EXTENSIONS]]
        resolved=[name for name in names if name in source]
    # Match the meaningful path suffix, not just common names such as route.ts.
    suffix='/'.join(part for part in requested.split('/') if part not in {'.','..'})
    candidates=[]
    if suffix and not resolved:
        for path in sorted(source):
            stem=path
            for ext in _EXTENSIONS:
                if stem.endswith(ext):stem=stem[:-len(ext)];break
            if stem.endswith('/index'):stem=stem[:-6]
            if stem!=suffix and not stem.endswith('/'+suffix):continue
            relative=posixpath.relpath(stem,posixpath.dirname(importer) or '.')
            if not relative.startswith('.'):relative='./'+relative
            item={'file':path,'relative_specifier':relative}
            if re.fullmatch(r'app/api/(?:[^/]+/)*route\.(?:ts|js)',path):
                item.update(module_kind='next_http_route',http_route='/'+path[4:].rsplit('/route.',1)[0],
                    boundary='HTTP handler module, not a client helper. Client components call its endpoint with fetch rather than importing handlers.')
            candidates.append(item)
    return {'requested_module':requested,'resolved_base':base,'existing_resolution':resolved,
        'existing_suffix_candidates':candidates[:5],'additional_candidates_omitted':max(0,len(candidates)-5),
        'scope':'Path facts only, not a repair instruction. Candidates may be unrelated; inspect actual exports and server/client boundaries. No files or dependencies were created.'}
