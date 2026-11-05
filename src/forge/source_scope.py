"""Select current source by module relationships; retain explicit omission hashes."""
import posixpath
import re


EXTENSIONS=('.ts','.tsx','.js','.jsx','.css')


def page_module(path):
    return path.startswith('app/') and path.rsplit('/',1)[-1] in {'page.tsx','page.jsx','page.ts','page.js'}


def resolve_import(importer,module,paths):
    if module.startswith('@/'):base=module[2:]
    elif module.startswith(('./','../')):base=posixpath.normpath(posixpath.join(posixpath.dirname(importer),module))
    else:return set()
    if base=='..' or base.startswith('../'):return set()
    candidates=[base,*[base+ext for ext in EXTENSIONS],*[base+'/index'+ext for ext in EXTENSIONS]]
    exact={path for path in candidates if path in paths}
    if exact:return exact
    # An unresolved relative import can be the defect. Include matching declared
    # modules as references without claiming that the original import resolves.
    suffix='/'.join(part for part in module.removeprefix('@/').split('/') if part not in {'.','..'})
    return {path for path in paths if any(path==suffix+ext or path.endswith('/'+suffix+ext) for ext in EXTENSIONS)}


def scope_source(snapshot,targets,manifest_paths,*,generating=False,interfaces=()):
    paths=set(snapshot)|set(manifest_paths)|set(targets);edges={}
    for path,packet in snapshot.items():
        content=packet.get('content') or ''
        imports=re.findall(r'''(?:\bfrom\s*|\bimport\s*\(\s*|\brequire\s*\(\s*|\bimport\s*)['"]([^'"]+)['"]''',content)
        edges[path]=set().union(*(resolve_import(path,module,paths) for module in imports)) if imports else set()
    selected=set(targets)
    if generating:
        # A new module has no import graph yet. Its imports/props must be chosen
        # from existing implementations, rather than invented from filenames.
        if interfaces:
            for interface in interfaces:
                endpoints={interface['provider'],*interface['consumers']}
                if endpoints.intersection(targets):selected.update(endpoints)
        else:selected.update(path for path in manifest_paths if path in snapshot)
    for target in targets:
        selected.update(edges.get(target,set()))
        selected.update(path for path,imports in edges.items() if target in imports)
        if target.endswith(('.css','.tsx')):
            selected.add('app/layout.tsx')
        if target.endswith('.css'):selected.add('app/page.tsx')
        if page_module(target) or target.startswith('app/components/'):
            selected.update(path for path in snapshot if path.startswith('app/api/') and '/route.' in path)
    # Shared declarations remain available even if a consumer has a missing import.
    selected.update(path for path,packet in snapshot.items()
        if re.search(r'\bexport\s+(?:type|interface)\s+\w+',packet.get('content') or ''))
    scoped={path:packet for path,packet in snapshot.items() if path in selected}
    omitted=[{'file':path,'sha256':packet['sha256'],
        'reason':'Outside this source task\'s direct imports, consumers, shared types and framework entry references. Complete read is saved in scoped tool reports.'}
        for path,packet in snapshot.items() if path not in selected]
    inventory=[{'file':path,'exists':path in snapshot,'sha256':snapshot[path]['sha256'] if path in snapshot else None}
        for path in sorted(paths)]
    return scoped,omitted,inventory
