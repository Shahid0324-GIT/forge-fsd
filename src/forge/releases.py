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


def preparation_graph(agents, store, job_id):
    def ci(state):
        record_handoff(store, job_id, 'verification_controller', 'ci_agent',
                       'Prepare generated-app CI from the approved contract and current evidence.', state['context'],agents=agents)
        store.event(job_id, 'CI_PLANNING', {'delegated_to':'ci_agent'}, update_status=False)
        notes = CINotes.model_validate(agents.generate(CINotes,
            'You are the generated-application CI Agent. Explain the supplied fixed CI policy: '
            'locked dependency provisioning, offline Docker typecheck/build, approved HTTP checks, '
            'and applicable restart/database checks. Do not invent execution results or emit YAML/commands. '
            'These are app checks, not Forge controller tests. HTTP acceptance checks assert response '
            'values/statuses; they do NOT authorize user requests or add authentication. Dependency '
            'provisioning uses network access; execution is offline. Do not imply otherwise. '
            'Discuss database/restart checks only if this supplied app uses SQLite. State limited coverage.', state['context']))
        return {'ci':notes.model_dump()}
    def deployment(state):
        context = {**state['context'], 'ci_agent':state['ci']}
        record_handoff(store, job_id, 'ci_agent', 'deployment_agent',
                       'Plan a separate approved Vercel deployment after generated-app CI.', context,agents=agents)
        store.event(job_id, 'DEPLOYMENT_PLANNING', {'delegated_to':'deployment_agent'}, update_status=False)
        notes = DeploymentNotes.model_validate(agents.generate(DeploymentNotes,
            'You are the generated-application Deployment Agent. Target Vercel. Explain only the supplied '
            'deployment eligibility and blockers. SQLite deployment is blocked until a remote database '
            'adapter is implemented; a URL alone is insufficient. Deployment needs its own approval, '
            'passing CI at the published commit and preconfigured Vercel project secrets. '
            'Never claim deployment has happened or request secret values.', context))
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
    fingerprint=release_gate(record,root)
    review=next(e['payload'] for e in reversed(record['events']) if e['status']=='PLAN_REVIEW')
    database=review['requirements'].get('database','sqlite')
    context={'job_id':job_id,'repository':repository,'source_fingerprint':fingerprint,
             'requirements':review['requirements'],'plan':review['plan'],
             'local_gates':'passed for this source','deployment_allowed':database=='none',
             'blockers':[] if database=='none' else ['Remote database adapter is not implemented; SQLite cannot persist on Vercel.']}
    with tracing_context(enabled=False):
        result=preparation_graph(agents,store,job_id).invoke({'context':context})
    if release_gate(store.read(job_id),root)!=fingerprint:raise ValueError('Source changed during release preparation')
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
    for name in ['verify.mjs','application.mjs','tasks.mjs','database.mjs','platform-reference.txt']:
        shutil.copyfile(PROJECT/'tests/acceptance'/name,acceptance/name)
    dependencies=bundle/'.forge/dependencies';dependencies.mkdir()
    shutil.copyfile(PROJECT/'templates/task-app/Dockerfile.dependencies',dependencies/'Dockerfile.dependencies')
    for name in ['package.json','package-lock.json']:
        if (root/name).read_bytes()!=(PROJECT/'templates/task-app'/name).read_bytes():raise ValueError('Release dependencies differ from the verified fixed platform')
        shutil.copyfile(root/name,dependencies/name)
    generic=review['requirements'].get('spec_version')==2
    (bundle/'.forge/contract.json').write_text(json.dumps({'requirements':review['requirements'],'plan':review['plan']}),encoding='utf-8')
    workflows=bundle/'.github/workflows';workflows.mkdir(parents=True)
    (workflows/'app-ci.yml').write_text(ci_workflow(generic),encoding='utf-8')
    if database=='none':(workflows/'deploy.yml').write_text(deploy_workflow(),encoding='utf-8')
    (bundle/'.gitignore').write_text('node_modules/\n.next/\n.vercel/\n.env*\n!.env.example\ndata/\n*.sqlite*\n',encoding='utf-8')
    report={**context,'ci_agent':result['ci'],'deployment_agent':result['deployment'],
            'bundle_directory':str(bundle.resolve()),'bundle_fingerprint':source_fingerprint(bundle),
            'workflows':{path.name:path.read_text(encoding='utf-8') for path in sorted(workflows.glob('*.yml'))},
            'required_secret_names':sorted(SECRETS) if database=='none' else [],
            'cloud_deployed':False,'ci_executed':False,
            'limitations':['Hosted CI includes approved API checks, not a complete security audit or general browser coverage.',
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
    if release_gate(record,PROJECT/'workspace'/job_id)!=report['source_fingerprint']:raise ValueError('Generated source changed; prepare a new release')
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
    gh('repo','create',repository,'--private','--description','Application generated and verified by ForgeFSD')
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
