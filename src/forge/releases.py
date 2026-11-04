"""Agent-planned, controller-rendered CI/CD for generated applications.

Models produce bounded review notes, never executable workflow text or commands.
Publishing and deployment are separate explicit human decisions.
"""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import Field

from forge.builders import PROJECT
from forge.handoffs import record_handoff
from forge.schemas import Boundary
from forge.workspace import safe_path, source_fingerprint
from forge.tasks import TaskLedger,Task,Dependency,CheckEvidence,Observation

CHECKOUT = 'd23441a48e516b6c34aea4fa41551a30e30af803'
NODE = '249970729cb0ef3589644e2896645e5dc5ba9c38'
UPLOAD = 'b7c566a772e6b6bfb58ed0dc250532a479d7789f'
VERCEL_VERSION = '65.9.0'
SECRETS = {'VERCEL_TOKEN', 'VERCEL_ORG_ID', 'VERCEL_PROJECT_ID'}


class CINotes(Boundary):
    summary: str = Field(min_length=1, max_length=800)
    limitations: list[str] = Field(min_length=1, max_length=5)


class DeploymentNotes(CINotes):
    target: Literal['vercel']


class ReleaseState(TypedDict, total=False):
    context: dict
    ci: dict
    deployment: dict


def validate_repository(repository):
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9][A-Za-z0-9._-]{0,99}', repository):
        raise ValueError('Use an owner/repository name, not a URL or command')
    if repository.split('/')[1].endswith('.git'):
        raise ValueError('Repository name must omit .git')
    return repository


def release_gate(record, root):
    from forge.preview import check_preview_gate
    # A live preview does not grant permission to publish; use the same evidence gate.
    candidate = dict(record)
    if candidate['status'] == 'PREVIEW_RUNNING':candidate['status'] = 'PREVIEW_STOPPED'
    return check_preview_gate(candidate, root)


def source_release_gate(job_id,store,root):
    from forge.autonomous_planning import uses_autonomous_planning
    from forge.autonomous_testing import evidence_current
    record=store.read(job_id)
    if not uses_autonomous_planning(record):return release_gate(record,root)
    if record['status'] not in {'AUTONOMOUS_APP_CHECKS_PASSED','PREVIEW_RUNNING','PREVIEW_STOPPED','PREVIEW_FAILED'}:
        raise ValueError('Release preparation requires a complete current app-check pass')
    if not evidence_current(record,store,workspace_boundary=PROJECT/'workspace'):
        raise ValueError('Release preparation requires current source-bound build/browser evidence')
    return next(e['payload']['source_fingerprint'] for e in reversed(record['events']) if e['status']=='AUTONOMOUS_APP_CHECKS_PASSED')


def release_notes(agents,store,job_id,role,sender,summary,schema,instruction,context,parent=None):
    """Bind each autonomous release role to a real task, without shell capabilities."""
    ledger=TaskLedger(store,job_id)
    source=next(e['payload'] for e in reversed(store.read(job_id)['events']) if e['status']=='AUTONOMOUS_APP_CHECKS_PASSED')
    upstream=ledger.read(parent or source['task_id'])
    context_hash=hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()
    inputs={'source_fingerprint':context['source_fingerprint'],'repository':context['repository'],'context_fingerprint':context_hash}
    matches=[task for task in ledger.list() if task.task.owner==role and task.task.parent_id==upstream.task.id
        and task.task.inputs==inputs and any(d.task_id==upstream.task.id and d.revision==upstream.revision for d in task.task.dependencies)
        and task.status in {'completed','paused'}]
    if len(matches)>1:raise ValueError('Multiple release role checkpoints need reconciliation')
    current=matches[0] if matches else None
    if current and current.status=='completed':
        path=store.path.parent/'release-notes'/job_id/(current.task.id+'.json');raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=current.observations[-1].fingerprint:raise ValueError('Saved release notes changed; inspect the checkpoint')
        notes=schema.model_validate(json.loads(raw)['notes'])
        store.event(job_id,'RELEASE_NOTES_REUSED',{'task_id':current.task.id,'context_fingerprint':context_hash},update_status=False)
        return notes,current.task.id
    if current:
        state=ledger.reserve_action(ledger.start(ledger.resume(current,additional_actions=1)),role)
        context={**context,'previous_role_errors':[o.error for o in state.observations if o.revision==state.revision and o.error][-2:]}
    else:
        state=ledger.reserve_action(ledger.start(ledger.create(Task(owner=role,parent_id=upstream.task.id,
            goal=summary,inputs=inputs,dependencies=[Dependency(task_id=upstream.task.id,revision=upstream.revision)],required_checks=['release_notes']))),role)
    previous=getattr(agents,'invocation_context',{});activity=getattr(agents,'activity',None)
    try:
        record_handoff(store,job_id,sender,role,summary,context,agents=agents,task_id=state.task.id,parent_task_id=upstream.task.id,task_state=state)
        agents.activity=lambda status,payload:store.event(job_id,status,payload,update_status=False)
        notes=schema.model_validate(agents.generate(schema,instruction,context))
        ledger.assert_active(state)
        path=store.path.parent/'release-notes'/job_id/(state.task.id+'.json');path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'notes':notes.model_dump(),'source_fingerprint':context['source_fingerprint'],
            'scope':'Validated planning notes only; no CI run or deployment is claimed.'},indent=2),encoding='utf-8')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        ledger.observe(state,Observation(revision=state.revision,fingerprint=digest,checks=[CheckEvidence(
            check='release_notes',exit_code=0,fingerprint=digest,report=str(path.resolve()),summary='Planning notes validated; execution is separate.')]))
        return notes,state.task.id
    except Exception as exc:
        try:
            current=ledger.read(state.task.id)
            if current.status=='running':
                current=ledger.observe(current,Observation(revision=current.revision,fingerprint=context['source_fingerprint'],error=f'{type(exc).__name__}: {exc}'[:2000]))
                ledger.pause(current,'Release role needs correction; no release bundle approved')
        except Exception:pass
        raise
    finally:agents.invocation_context=previous;agents.activity=activity


def preparation_graph(agents, store, job_id):
    ci_task=None
    def ci(state):
        nonlocal ci_task
        if not state['context'].get('autonomous'):record_handoff(store, job_id, 'verification_controller', 'ci_agent',
                       'Prepare generated-app CI from the approved contract and current evidence.', state['context'],agents=agents)
        store.event(job_id, 'CI_PLANNING', {'delegated_to':'ci_agent'}, update_status=False)
        instruction=(
            'You are the generated-application CI Agent. Explain the supplied fixed CI policy: '
            'locked dependency provisioning, offline Docker typecheck/build, approved HTTP checks, '
            'and applicable restart/database checks. Do not invent execution results or emit YAML/commands. '
            'These are app checks, not Forge controller tests. HTTP acceptance checks assert response '
            'values/statuses; they do NOT authorize user requests or add authentication. Dependency '
            'provisioning uses network access; execution is offline. Do not imply otherwise. '
            'Discuss database/restart checks only if this supplied app uses SQLite. State limited coverage.')
        if state['context'].get('autonomous'):
            instruction='Explain only this fixed CI policy: locked dependency provisioning, offline TypeScript/production build and GET / homepage smoke. There are zero hosted API scenarios and no hosted browser replay; browser acceptance already ran locally. Do not claim CI executed, security audits or deployment. Return bounded review notes, never YAML or commands.'
            notes,ci_task=release_notes(agents,store,job_id,'ci_agent','verification_controller',
                'Prepare generated-app CI from the current verified source and explicit limited CI policy.',CINotes,instruction,state['context'])
        else:notes=CINotes.model_validate(agents.generate(CINotes,instruction,state['context']))
        return {'ci':notes.model_dump()}
    def deployment(state):
        context = {**state['context'], 'ci_agent':state['ci']}
        if not context.get('autonomous'):record_handoff(store, job_id, 'ci_agent', 'deployment_agent',
                       'Plan a separate approved Vercel deployment after generated-app CI.', context,agents=agents)
        store.event(job_id, 'DEPLOYMENT_PLANNING', {'delegated_to':'deployment_agent'}, update_status=False)
        instruction=(
            'You are the generated-application Deployment Agent. Target Vercel. Explain only the supplied '
            'deployment eligibility and blockers. SQLite deployment is blocked until a remote database '
            'adapter is implemented; a URL alone is insufficient. Deployment needs its own approval, '
            'passing CI at the published commit and preconfigured Vercel project secrets. '
            'Never claim deployment has happened or request secret values.')
        if context.get('autonomous'):
            notes,_=release_notes(agents,store,job_id,'deployment_agent','ci_agent',
                'Plan a separately approved stateless Vercel deployment after generated-app CI.',DeploymentNotes,instruction,context,parent=ci_task)
        else:notes=DeploymentNotes.model_validate(agents.generate(DeploymentNotes,instruction,context))
        return {'deployment':notes.model_dump()}
    graph = StateGraph(ReleaseState)
    graph.add_node('ci_agent',ci);graph.add_node('deployment_agent',deployment)
    graph.add_edge(START,'ci_agent');graph.add_edge('ci_agent','deployment_agent');graph.add_edge('deployment_agent',END)
    return graph.compile()


def ci_workflow(generic):
    contract = '\n            --env FORGE_APP_CONTRACT=/contract.json --mount "type=bind,source=$PWD/.forge/contract.json,target=/contract.json,readonly" \\' if generic else ''
    return f'''name: Generated app CI
'on':
  push:
  pull_request:
  workflow_dispatch:
  workflow_call:
permissions:
  contents: read
jobs:
  app:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@{CHECKOUT}
        with:
          persist-credentials: false
      - name: Provision locked dependencies (network enabled, no lifecycle scripts)
        run: docker build --file .forge/dependencies/Dockerfile.dependencies --tag forge-app-ci .forge/dependencies
      - name: Typecheck, build and exercise the approved application contract offline
        run: |
          set -eu
          docker run --rm --network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges \\
            --user=1000:1000 --memory=6g --cpus=2 --pids-limit=256 \\
            --tmpfs /tmp:rw,noexec,nosuid,size=256m,uid=1000,gid=1000 \\
            --tmpfs /work:rw,nosuid,size=2g,uid=1000,gid=1000 \\
            --env NEXT_TELEMETRY_DISABLED=1 --env SQLITE_PATH=/work/data/app.sqlite3 \\{contract}
            --mount "type=bind,source=$PWD,target=/source,readonly" \\
            --mount "type=bind,source=$PWD/.forge/acceptance,target=/trusted,readonly" \\
            --workdir /work forge-app-ci /bin/sh -c \\
            'cp -R /source/. /work/ && ln -s /opt/forge-deps/node_modules /work/node_modules && node /trusted/verify.mjs'
'''


def deploy_workflow():
    return f'''name: Deploy generated app
run-name: Deploy ${{{{ inputs.approved_sha }}}}
'on':
  workflow_dispatch:
    inputs:
      approved_sha:
        description: Exact published commit approved in Forge
        required: true
        type: string
permissions:
  contents: read
jobs:
  verify:
    uses: ./.github/workflows/app-ci.yml
  deploy:
    needs: verify
    if: github.ref == 'refs/heads/main' && github.sha == inputs.approved_sha
    runs-on: ubuntu-latest
    timeout-minutes: 20
    environment: production
    env:
      VERCEL_TOKEN: ${{{{ secrets.VERCEL_TOKEN }}}}
      VERCEL_ORG_ID: ${{{{ secrets.VERCEL_ORG_ID }}}}
      VERCEL_PROJECT_ID: ${{{{ secrets.VERCEL_PROJECT_ID }}}}
    steps:
      - uses: actions/checkout@{CHECKOUT}
        with:
          persist-credentials: false
      - uses: actions/setup-node@{NODE}
        with:
          node-version: '24'
      - name: Check deployment configuration
        run: test -n "$VERCEL_TOKEN" && test -n "$VERCEL_ORG_ID" && test -n "$VERCEL_PROJECT_ID"
      - name: Pull production settings
        run: npx --yes vercel@{VERCEL_VERSION} pull --yes --environment=production --token="$VERCEL_TOKEN"
      - name: Build deployment output
        run: npx --yes vercel@{VERCEL_VERSION} build --prod --token="$VERCEL_TOKEN"
      - name: Deploy approved application
        run: |
          npx --yes vercel@{VERCEL_VERSION} deploy --prebuilt --prod --token="$VERCEL_TOKEN" > deployment-url.txt
          node -e "const fs=require('fs');const url=fs.readFileSync('deployment-url.txt','utf8').trim();if(!/^https:\\/\\/[a-zA-Z0-9.-]+\\.vercel\\.app$/.test(url))throw Error('Unexpected deployment URL');fs.writeFileSync('deployment.json',JSON.stringify({{url,sha:process.env.GITHUB_SHA}}))"
      - uses: actions/upload-artifact@{UPLOAD}
        with:
          name: deployment
          path: deployment.json
          retention-days: 7
'''


def _save_report(directory, name, report):
    path = directory/name
    path.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return str(path.resolve())


def prepare_release(job_id, agents, store, repository):
    validate_repository(repository)
    record=store.read(job_id);root=PROJECT/'workspace'/job_id
    fingerprint=source_release_gate(job_id,store,root)
    from forge.autonomous_planning import uses_autonomous_planning
    autonomous=uses_autonomous_planning(record)
    if autonomous:
        from forge.autonomous_review import approved_review
        approved=approved_review(job_id,store)
        if approved['draft']['database']!='none':raise ValueError('Autonomous release preparation currently supports stateless apps; SQLite CI/deployment adapters remain pending')
        review={'requirements':{'spec_version':2,'database':'none','pages':['/'],'entities':[],'scenarios':[]},'plan':approved['draft']}
    else:review=next(e['payload'] for e in reversed(record['events']) if e['status']=='PLAN_REVIEW')
    database=review['requirements'].get('database','sqlite')
    context={'job_id':job_id,'repository':repository,'source_fingerprint':fingerprint,
             'requirements':review['requirements'],'plan':review['plan'],
             'local_gates':'passed for this source','deployment_allowed':database=='none',
             'blockers':[] if database=='none' else ['Remote database adapter is not implemented; SQLite cannot persist on Vercel.'],
             **({'autonomous':True,'ci_policy':'Offline typecheck/build and homepage HTTP smoke only. Local frozen browser checks are separate; no hosted API scenarios or browser replay.'} if autonomous else {})}
    with tracing_context(enabled=False):
        result=preparation_graph(agents,store,job_id).invoke({'context':context})
    if source_release_gate(job_id,store,root)!=fingerprint:raise ValueError('Source changed during release preparation')
    directory=PROJECT/'artifacts/releases'/job_id/uuid4().hex;bundle=directory/'bundle';bundle.mkdir(parents=True)
    # Explicitly bounded, verified source only; never copy local credentials or build directories.
    for path in root.rglob('*'):
        relative=path.relative_to(root).as_posix();safe_path(root,relative)
        if path.is_file():
            if any(part in {'.git','node_modules','.next','.vercel','data','.forge','.github'} for part in path.relative_to(root).parts):raise ValueError('Unexpected generated release content')
            if path.name.startswith('.env') and path.name!='.env.example':raise ValueError('Environment files cannot be published')
            if path.suffix in {'.db','.sqlite','.sqlite3','.pem','.key'}:raise ValueError('Runtime data or keys cannot be published')
            target=bundle/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(path.read_bytes())
    acceptance=bundle/'.forge/acceptance';acceptance.mkdir(parents=True)
    for name in ['verify.mjs','application.mjs','tasks.mjs','database.mjs','platform-reference.txt','homepage-smoke.mjs']:
        shutil.copyfile(PROJECT/'tests/acceptance'/name,acceptance/name)
    dependencies=bundle/'.forge/dependencies';dependencies.mkdir()
    shutil.copyfile(PROJECT/'templates/task-app/Dockerfile.dependencies',dependencies/'Dockerfile.dependencies')
    for name in ['package.json','package-lock.json']:
        if (root/name).read_bytes()!=(PROJECT/'templates/task-app'/name).read_bytes():raise ValueError('Release dependencies differ from the verified fixed platform')
        shutil.copyfile(root/name,dependencies/name)
    generic=review['requirements'].get('spec_version')==2
    (bundle/'.forge/contract.json').write_text(json.dumps({'requirements':review['requirements'],'plan':review['plan'],
        **({'verification_scope':'build-homepage-smoke'} if autonomous else {})}),encoding='utf-8')
    workflows=bundle/'.github/workflows';workflows.mkdir(parents=True)
    workflow=ci_workflow(generic)
    if autonomous:
        workflow=workflow.replace('name: Generated app CI','name: Generated app build CI').replace(
            'Typecheck, build and exercise the approved application contract offline',
            'Typecheck, build and homepage HTTP smoke (browser QA ran locally)')
    (workflows/'app-ci.yml').write_text(workflow,encoding='utf-8')
    if database=='none':(workflows/'deploy.yml').write_text(deploy_workflow(),encoding='utf-8')
    (bundle/'.gitignore').write_text('node_modules/\n.next/\n.vercel/\n.env*\n!.env.example\ndata/\n*.sqlite*\n',encoding='utf-8')
    report={**context,'ci_agent':result['ci'],'deployment_agent':result['deployment'],
            'bundle_directory':str(bundle.resolve()),'bundle_fingerprint':source_fingerprint(bundle),
            'workflows':{path.name:path.read_text(encoding='utf-8') for path in sorted(workflows.glob('*.yml'))},
            'required_secret_names':sorted(SECRETS) if database=='none' else [],
            'cloud_deployed':False,'ci_executed':False,
            'limitations':[('Hosted CI runs typecheck/build and homepage smoke only; local frozen browser checks are not replayed in hosted CI.' if autonomous else 'Hosted CI includes approved API checks, not a complete security audit or general browser coverage.'),
                           'Vercel project creation/linking and project secrets must be configured before deployment.',
                           'Vercel CLI is version-pinned; its transient transitive dependencies are resolved during deployment.']}
    report['release_fingerprint']=hashlib.sha256(json.dumps(report,sort_keys=True).encode()).hexdigest()
    path=_save_report(directory,'review.json',report)
    store.event(job_id,'RELEASE_REVIEW',{'report':path,'release_fingerprint':report['release_fingerprint'],
                'repository':repository,'deployment_allowed':report['deployment_allowed'],'source_fingerprint':fingerprint},update_status=False)
    return store.read(job_id)


def reviewed_release(job_id,store,fingerprint):
    record=store.read(job_id)
    payload=next((e['payload'] for e in reversed(record['events']) if e['status']=='RELEASE_REVIEW'),None)
    if not payload or payload['release_fingerprint']!=fingerprint:raise ValueError('Review the current release before approving')
    report=json.loads(Path(payload['report']).read_text(encoding='utf-8'))
    original=dict(report);original.pop('release_fingerprint')
    if hashlib.sha256(json.dumps(original,sort_keys=True).encode()).hexdigest()!=fingerprint:raise ValueError('Release review changed')
    bundle=Path(report['bundle_directory']);expected=(PROJECT/'artifacts/releases'/job_id).resolve()
    if not bundle.resolve().is_relative_to(expected):raise ValueError('Release bundle is outside its boundary')
    if source_fingerprint(bundle)!=report['bundle_fingerprint']:raise ValueError('Release bundle changed; prepare a new review')
    if source_release_gate(job_id,store,PROJECT/'workspace'/job_id)!=report['source_fingerprint']:raise ValueError('Generated source changed; prepare a new release')
    return report,bundle


def command(args,cwd=None):
    result=subprocess.run(args,cwd=cwd,capture_output=True,text=True,timeout=120)
    if result.returncode:raise ValueError('Release operation failed: '+result.stderr[-1200:])
    return result.stdout.strip()


def gh(*args):
    executable=shutil.which('gh')
    if not executable and Path('C:/Program Files/GitHub CLI/gh.exe').is_file():executable='C:/Program Files/GitHub CLI/gh.exe'
    if not executable:raise ValueError('GitHub CLI is not installed')
    return command([executable,*args])


def create_private_repository(repository):
    # Use the REST create endpoint; GraphQL failures must not cause adoption of
    # an existing destination or a force push.
    return gh('api','user/repos','--method','POST','-f',f'name={repository.split("/")[1]}',
        '-F','private=true','-f','description=Application generated and verified by ForgeFSD')


def publish_release(job_id,store,fingerprint,approved=False):
    if approved is not True:raise ValueError('Publishing requires separate explicit approval')
    report,bundle=reviewed_release(job_id,store,fingerprint)
    if any(e['status']=='RELEASE_PUBLISH_STARTED' for e in store.read(job_id)['events']):
        raise ValueError('Publishing was already attempted; inspect the remote before retrying')
    repository=validate_repository(report['repository'])
    login=gh('api','user','--jq','.login')
    if repository.split('/')[0].lower()!=login.lower():raise ValueError('POC publishing only supports the signed-in personal account')
    if repository.lower()==f'{login}/forge-fsd'.lower():raise ValueError('The Forge controller repository is not an application destination')
    export=bundle.parent/'publish';shutil.copytree(bundle,export)
    command(['git','init','-b','main'],export)
    command(['git','-c','core.autocrlf=false','add','.'],export)
    command(['git','-c','user.name=ForgeFSD','-c',f'user.email={login}@users.noreply.github.com','commit','-m','Publish approved generated application'],export)
    sha=command(['git','rev-parse','HEAD'],export)
    store.event(job_id,'RELEASE_PUBLISH_STARTED',{'repository':repository,'sha':sha,'release_fingerprint':fingerprint,'approved_by':'local_dashboard'},update_status=False)
    # Creates a NEW private repo only. Never overwrite an existing remote or force-push.
    create_private_repository(repository)
    command(['git','remote','add','origin',f'https://github.com/{repository}.git'],export)
    command(['git','push','-u','origin','main'],export)
    store.event(job_id,'APP_PUBLISHED',{'repository':repository,'sha':sha,'release_fingerprint':fingerprint,
                'url':f'https://github.com/{repository}','source_fingerprint':report['source_fingerprint']},update_status=False)
    return store.read(job_id)


def published_release(job_id,store,fingerprint):
    report,_=reviewed_release(job_id,store,fingerprint)
    published=next((e['payload'] for e in reversed(store.read(job_id)['events']) if e['status']=='APP_PUBLISHED' and e['payload']['release_fingerprint']==fingerprint),None)
    if not published:raise ValueError('Publish this reviewed app before deployment')
    remote=json.loads(gh('api',f'repos/{published["repository"]}/commits/main'))
    if remote.get('sha')!=published['sha']:raise ValueError('Remote main changed after publishing; a new release review is required')
    return report,published


def resume_failed_repository_creation(job_id,store,fingerprint,*,approved=False):
    """Resume only a failed create against a still-absent remote; never adopt a repo."""
    if approved is not True:raise ValueError('Publishing recovery requires explicit approval')
    report,bundle=reviewed_release(job_id,store,fingerprint)
    events=store.read(job_id)['events']
    attempts=[e['payload'] for e in events if e['status']=='RELEASE_PUBLISH_STARTED']
    if len(attempts)!=1 or attempts[0]['release_fingerprint']!=fingerprint:
        raise ValueError('Inspect publishing attempts before recovery')
    if any(e['status']=='APP_PUBLISHED' for e in events):raise ValueError('Application is already published')
    pending=attempts[0];repository=validate_repository(report['repository'])
    if pending['repository']!=repository:raise ValueError('Publishing destination changed')
    login=gh('api','user','--jq','.login')
    if repository.split('/')[0].lower()!=login.lower() or repository.lower()==f'{login}/forge-fsd'.lower():
        raise ValueError('Publishing recovery requires the same personal app destination')
    export=bundle.parent/'publish'
    if command(['git','rev-parse','HEAD'],export)!=pending['sha'] or command(['git','status','--porcelain','--untracked-files=all'],export):
        raise ValueError('Prepared publishing commit changed')
    try:gh('api',f'repos/{repository}')
    except ValueError as exc:
        if 'HTTP 404' not in str(exc):raise
    else:raise ValueError('Remote exists; inspect it manually instead of adopting or overwriting it')
    store.event(job_id,'RELEASE_CREATE_RESUMED',{'repository':repository,'sha':pending['sha'],'release_fingerprint':fingerprint},update_status=False)
    create_private_repository(repository)
    command(['git','remote','add','origin',f'https://github.com/{repository}.git'],export)
    command(['git','push','-u','origin','main'],export)
    store.event(job_id,'APP_PUBLISHED',{'repository':repository,'sha':pending['sha'],'release_fingerprint':fingerprint,
        'url':f'https://github.com/{repository}','source_fingerprint':report['source_fingerprint']},update_status=False)
    return store.read(job_id)


def app_ci(job_id,store,fingerprint):
    report,published=published_release(job_id,store,fingerprint)
    rows=json.loads(gh('run','list','--repo',published['repository'],'--workflow','app-ci.yml','--commit',published['sha'],
                       '--limit','20','--json','databaseId,status,conclusion,url,headSha,event'))
    runs=[r for r in rows if r['headSha']==published['sha'] and r['event'] in {'push','workflow_dispatch'}]
    # A newer failed/pending rerun supersedes an older passing result.
    latest=runs[0] if runs else None
    store.event(job_id,'APP_CI_STATUS',{'release_fingerprint':fingerprint,'repository':published['repository'],'sha':published['sha'],
                'run':latest,'passed':bool(latest and latest['status']=='completed' and latest['conclusion']=='success')},update_status=False)
    return latest


def deploy_release(job_id,store,fingerprint,approved=False):
    if approved is not True:raise ValueError('Public production deployment requires separate explicit approval')
    report,published=published_release(job_id,store,fingerprint)
    if not report['deployment_allowed']:raise ValueError('Deployment blocked: remote database adapter is not implemented')
    existing=next((e for e in store.read(job_id)['events'] if e['status'] in {'DEPLOYMENT_APPROVED','DEPLOYMENT_DISPATCHED'} and e['payload']['release_fingerprint']==fingerprint),None)
    if existing:raise ValueError('Deployment already dispatched or attempted; inspect its status before another attempt')
    run=app_ci(job_id,store,fingerprint)
    if not run or run['status']!='completed' or run['conclusion']!='success':raise ValueError('Generated app CI must pass at the exact published commit')
    secrets=json.loads(gh('secret','list','--repo',published['repository'],'--json','name'))
    if not SECRETS.issubset({item['name'] for item in secrets}):raise ValueError('Configure repository secrets: '+', '.join(sorted(SECRETS)))
    store.event(job_id,'DEPLOYMENT_APPROVED',{'release_fingerprint':fingerprint,'sha':published['sha'],'approved_by':'local_dashboard'},update_status=False)
    approved_at=store.read(job_id)['events'][-1]['timestamp'][:19]+'Z'
    gh('workflow','run','deploy.yml','--repo',published['repository'],'--ref','main','-f',f'approved_sha={published["sha"]}')
    store.event(job_id,'DEPLOYMENT_DISPATCHED',{'release_fingerprint':fingerprint,'sha':published['sha'],'repository':published['repository'],'requested_after':approved_at},update_status=False)
    return store.read(job_id)


def refresh_release(job_id,store,fingerprint):
    _,published=published_release(job_id,store,fingerprint)
    app_ci(job_id,store,fingerprint)
    removed=next((e['payload'] for e in reversed(store.read(job_id)['events']) if e['status']=='APP_DEPLOYMENT_REMOVED' and e['payload']['release_fingerprint']==fingerprint),None)
    if removed:
        # Keep historical deployment evidence without reviving its URL after cleanup.
        store.event(job_id,'APP_DEPLOYMENT_STATUS',{'release_fingerprint':fingerprint,
                    'cloud_deployed':False,'removed':True,'cleanup':removed},update_status=False)
        return store.read(job_id)
    dispatch=next((e for e in reversed(store.read(job_id)['events']) if e['status']=='DEPLOYMENT_DISPATCHED' and e['payload']['release_fingerprint']==fingerprint),None)
    if dispatch:
        runs=json.loads(gh('run','list','--repo',published['repository'],'--workflow','deploy.yml','--commit',published['sha'],
                          '--limit','20','--json','databaseId,status,conclusion,url,headSha,displayTitle,createdAt,event'))
        matches=[r for r in runs if r['headSha']==published['sha'] and r['event']=='workflow_dispatch'
                 and r['displayTitle']=='Deploy '+published['sha'] and r['createdAt']>=dispatch['payload']['requested_after']]
        run=matches[0] if matches else None
        # A successful Actions run alone is not proof of deployment: require its URL artifact.
        payload={'release_fingerprint':fingerprint,'run':run,'cloud_deployed':False}
        if run and run['status']=='completed' and run['conclusion']=='success':
            directory=PROJECT/'artifacts/releases'/job_id/'deployments'/str(run['databaseId'])
            if not directory.exists():gh('run','download',str(run['databaseId']),'--repo',published['repository'],'--name','deployment','--dir',str(directory))
            result=json.loads((directory/'deployment.json').read_text(encoding='utf-8'))
            if result.get('sha')!=published['sha'] or not re.fullmatch(r'https://[a-zA-Z0-9.-]+\.vercel\.app',result.get('url','')):raise ValueError('Deployment evidence does not match approved commit')
            payload.update(cloud_deployed=True,url=result['url'])
        store.event(job_id,'APP_DEPLOYMENT_STATUS',payload,update_status=False)
    return store.read(job_id)
