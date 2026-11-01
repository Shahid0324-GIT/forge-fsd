import hashlib
import json
import shutil
import re
from pathlib import Path, PurePosixPath

from forge.schemas import Boundary
from pydantic import Field


OWNERS = {
    "frontend": {"app/page.tsx", "app/components/task-form.tsx"},
    "backend": {"lib/db.ts", "lib/tasks.ts", "app/api/tasks/route.ts", "app/api/tasks/[id]/route.ts"},
}


class FileOperation(Boundary):
    content: str = Field(min_length=1, max_length=24000)


def safe_path(root: Path, relative: str):
    parts = relative.split("/")
    if "\\" in relative or ":" in relative or PurePosixPath(relative).is_absolute() or any(p in {"", ".", ".."} for p in parts):
        raise ValueError("Unsafe workspace path")
    root = root.absolute()
    for candidate in (root, *root.parents):
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("Workspace ancestors may not be symlinks or junctions")
    target = root.joinpath(*parts)
    for candidate in (target, *target.parents):
        if candidate == root.parent:
            break
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("Workspace paths may not traverse links")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Workspace escape")
    return target


def plan_owners(plan):
    if plan.spec_version==1:return OWNERS
    return {owner:{file for task in plan.tasks if task.owner==owner for file in task.files} for owner in OWNERS}


def ordered_owner_files(plan,owner):
    files=list(dict.fromkeys(file for task in plan.tasks if task.owner==owner for file in task.files))
    # Stable within each group; providers occasionally list entry points before helpers.
    return sorted(files,key=lambda file:not file.startswith('lib/')) if owner=='backend' else sorted(files,key=lambda file:file.endswith('/page.tsx'))


def unsupported_imports(root,relative,content):
    """Dependency preflight, not a complete TypeScript parser or security scanner."""
    # Tie `from` to an import/export declaration. A JSX attribute or local variable
    # named `from` is not a module specifier. This remains a limited literal check.
    imports=re.findall(r'\b(?:import|export)\b\s*(?:[\w${},*]|\s)+?\bfrom\s*[\'\"]([^\'\"\r\n]+)[\'\"]|\b(?:import|require)\s*\(\s*[\'\"]([^\'\"]+)[\'\"]|\bimport\s*[\'\"]([^\'\"]+)[\'\"]',content)
    rejected=set()
    builtins={'assert','assert/strict','buffer','crypto','events','fs','fs/promises','os','path','perf_hooks','querystring','stream','stream/promises','string_decoder','timers','timers/promises','url','util'}
    for pair in imports:
        module=next(value for value in pair if value)
        if module.startswith('node:'):
            if module.split(':',1)[1] in {'child_process','worker_threads','cluster','vm'}:rejected.add(module)
        elif module.startswith('@/'):
            if not root.joinpath(module[2:]).resolve().is_relative_to(root.resolve()):rejected.add(module)
        elif module in builtins or module in {'next','react','react-dom'} or module.startswith(('next/','react/','react-dom/')):continue
        elif module.startswith('.'):
            if not (root/relative).parent.joinpath(module).resolve().is_relative_to(root.resolve()):rejected.add(module)
        else:rejected.add(module)
    return sorted(rejected)


def app_coding_context(requirements,plan,root,relative,limit=14000,*,extra=None,required=False,priority=()):
    """Keep complete contracts; include only whole source files that fit the input budget."""
    summary={key:requirements[key] for key in ['title','database','pages','entities','acceptance_criteria']}
    examples=[]
    for scenario in requirements['scenarios']:
        steps=[]
        for step in scenario['steps']:
            item={key:step[key] for key in ['method','path','status']}
            for source,target in [('body_json','input'),('expect_json','expected')]:
                if step.get(source):item[target]=json.loads(step[source])
            for key in ['contains','save_as','save_pointer','body_bindings','expect_bindings']:
                if step.get(key):item[key]=step[key]
            steps.append(item)
        examples.append({'name':scenario['name'],'phase':scenario.get('phase','functional'),'steps':steps})
    summary['acceptance_examples']=examples
    reference=Path(__file__).resolve().parents[2]/'tests/acceptance/platform-reference.txt'
    result={'file':relative,'requirements':summary,'plan':plan,'platform_reference':reference.read_text(encoding='utf-8'),
            'existing_source':{},'context_omitted':[]}
    if extra:result['repair']=extra
    size=lambda:len(json.dumps(result,separators=(',',':')))
    if size()>limit:raise ValueError('Approved contracts exceed the local coding context budget; simplify the plan before generation')
    files=list(dict.fromkeys(file for task in plan['tasks'] for file in task['files']))
    frontend=relative.startswith('app/') and not relative.startswith('app/api/')
    files.sort(key=lambda path:(path!=relative if required else False,path not in priority,
                               (path.startswith(('lib/','app/api/')) if frontend else not path.startswith('lib/')),path))
    if required and (relative not in files or not safe_path(root,relative).is_file()):
        raise ValueError('Repair target must be an existing approved source file')
    for file in files:
        path=safe_path(root,file)
        if not path.exists():continue
        if path.stat().st_size>24000:
            if required and file==relative:raise ValueError('Complete repair target exceeds the local coding context budget')
            result['context_omitted'].append(file);continue
        result['existing_source'][file]=path.read_text(encoding='utf-8')
        if size()>limit:
            del result['existing_source'][file]
            if required and file==relative:raise ValueError('Complete repair target exceeds the local coding context budget')
            result['context_omitted'].append(file)
    if size()>limit:raise ValueError('Source context metadata exceeds the local coding context budget')
    return result


def normalize_app_source(relative,content):
    """Normalize a single code fence and client syntax, never domain behavior."""
    fence=re.fullmatch(r'\s*((?:[\'\"]use client[\'\"];\s*)?)```(?:typescript|tsx|ts|jsx|javascript)?\s*\n([\s\S]*?)\n```\s*',content)
    if fence:content=fence.group(1)+fence.group(2)+'\n'
    if not relative.startswith('app/') or relative.startswith('app/api/') or not relative.endswith('.tsx'):
        return content
    content=re.sub(r'\A(\s*)use client\s*;',r'\1"use client";',content,count=1)
    hooks=r'\b(?:useState|useEffect|useReducer|useRef|useContext|useMemo|useCallback|useTransition|useSyncExternalStore|useRouter|usePathname|useSearchParams)\b'
    explicit_client=bool(re.match(r'\s*[\'\"]use client[\'\"]\s*;',content))
    interactive=bool(re.search(hooks,content) and re.search(r'from\s+[\'\"](?:react|next/navigation)[\'\"]',content))
    if not explicit_client and not interactive:return content
    runtime_source=re.sub(r'import\s+type\s+[^;]+;','',content)
    if re.search(r'[\'\"]use server[\'\"]|process\.env|from\s+[\'\"](?:node:|fs[\'\"]|path[\'\"]|@/lib/|\.{1,2}/.*lib/)',runtime_source):
        raise ValueError('Mixed server/client module requires explicit review; refusing to change its execution boundary')
    if explicit_client:return content
    return '"use client";\n'+content


def write_owned(root, owner, relative, content, owners=None):
    if relative not in (owners if owners is not None else OWNERS).get(owner,set()):
        raise ValueError("File outside builder ownership")
    target = safe_path(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(FileOperation(content=content).content, encoding="utf-8")


def seed_workspace(template, root, *, generic=False):
    if root.exists():
        raise ValueError("Workspace already exists; refusing to overwrite it")
    safe_path(root, "package.json")
    root.mkdir(parents=True)
    for source in template.rglob("*"):
        if source.is_symlink() or source.is_junction():
            raise ValueError("Template links are not allowed")
        if source.is_file():
            if generic and source.relative_to(template).as_posix() not in {'package.json','package-lock.json','tsconfig.json','next-env.d.ts','next.config.ts','app/layout.tsx','app/globals.css','app/api/health/route.ts'}:
                continue
            target = safe_path(root, source.relative_to(template).as_posix())
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            if generic and source.relative_to(template).as_posix()=='app/layout.tsx':
                target.write_text(target.read_text(encoding='utf-8').replace('Forge Tasks','Forge Application').replace('Generated task manager','Generated small application'),encoding='utf-8')


def source_fingerprint(root):
    entries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Unexpected link in source")
        if path.is_file():
            entries.append((path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()
