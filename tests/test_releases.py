import json
import shutil
from pathlib import Path

import pytest
import yaml

import forge.releases as release
from forge.persistence import JobStore
from forge.workspace import seed_workspace, source_fingerprint
from test_general_apps import calculator_spec, calculator_plan


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    actual = release.PROJECT
    shutil.copytree(actual/'templates', tmp_path/'templates')
    shutil.copytree(actual/'tests/acceptance', tmp_path/'tests/acceptance')
    monkeypatch.setattr(release, 'PROJECT', tmp_path)
    monkeypatch.setattr(release, 'release_gate', lambda record, root: source_fingerprint(root))
    store = JobStore(tmp_path/'artifacts/jobs.db');job = store.create()
    root = tmp_path/'workspace'/job
    seed_workspace(tmp_path/'templates/task-app', root, generic=True)
    store.event(job,'PLAN_REVIEW',{'requirements':calculator_spec(),'plan':calculator_plan()})
    store.event(job,'SECURITY_PASSED',{})
    class Agents:
        def __init__(self):self.calls=[]
        def generate(self,schema,instruction,data):
            self.calls.append((schema,data))
            notes={'summary':'Use the supplied fixed policy.','limitations':['Coverage is bounded.']}
            if schema is release.DeploymentNotes:notes['target']='vercel'
            return schema.model_validate(notes)
    agents=Agents()
    return tmp_path, store, job, root, agents


def prepare(fixture, database='none'):
    project,store,job,root,agents=fixture
    if database!='none':
        record=store.read(job);review=record['events'][1]['payload']
        review['requirements']['database']=database
        store.event(job,'PLAN_REVIEW',review,update_status=False)
    release.prepare_release(job,agents,store,'person/generated-app')
    payload=store.read(job)['events'][-1]['payload']
    return release.reviewed_release(job,store,payload['release_fingerprint'])


def test_agents_handoff_contract_and_render_app_ci_without_modifying_app(prepared):
    _,store,job,root,agents=prepared;before=source_fingerprint(root)
    report,bundle=prepare(prepared)
    assert source_fingerprint(root)==before
    assert [schema for schema,_ in agents.calls]==[release.CINotes,release.DeploymentNotes]
    assert agents.calls[1][1]['ci_agent']==report['ci_agent']
    assert store.read(job)['status']=='SECURITY_PASSED'
    handoffs=[e['payload'] for e in store.read(job)['events'] if e['status']=='AGENT_HANDOFF']
    assert [h['recipient'] for h in handoffs]==['ci_agent','deployment_agent']
    workflow=yaml.safe_load((bundle/'.github/workflows/app-ci.yml').read_text())
    assert 'workflow_call' in workflow['on']
    commands=workflow['jobs']['app']['steps'][-1]['run']
    assert '--network=none' in commands and '--cpus=2' in commands
    assert '/contract.json' in commands and '/trusted/verify.mjs' in commands
    assert 'pytest' not in commands and 'VERCEL_TOKEN' not in commands
    assert (bundle/'.forge/contract.json').is_file()
    assert report['deployment_allowed'] and not report['cloud_deployed']
    deploy=yaml.safe_load((bundle/'.github/workflows/deploy.yml').read_text())
    assert list(deploy['on'])==['workflow_dispatch']
    assert deploy['jobs']['deploy']['needs']=='verify'
    assert 'github.sha == inputs.approved_sha' in deploy['jobs']['deploy']['if']


def test_sqlite_has_ci_but_no_deploy_workflow(prepared):
    report,bundle=prepare(prepared,'sqlite')
    assert not report['deployment_allowed'] and report['blockers']
    assert (bundle/'.github/workflows/app-ci.yml').is_file()
    assert not (bundle/'.github/workflows/deploy.yml').exists()


@pytest.mark.parametrize('destination',['https://github.com/person/repo','person/../repo','person/repo;whoami','person/repo.git','-x/repo'])
def test_repository_rejects_paths_urls_and_commands(destination):
    with pytest.raises(ValueError):release.validate_repository(destination)


@pytest.mark.parametrize('change',['source','bundle','review'])
def test_stale_or_changed_release_cannot_be_published(prepared, change):
    _,store,job,root,_=prepared;report,bundle=prepare(prepared)
    if change=='source':(root/'app/page.tsx').write_text('changed')
    if change=='bundle':(bundle/'.github/workflows/app-ci.yml').write_text('changed')
    if change=='review':
        path=Path(store.read(job)['events'][-1]['payload']['report'])
        value=json.loads(path.read_text());value['repository']='attacker/app';path.write_text(json.dumps(value))
    with pytest.raises(ValueError):release.reviewed_release(job,store,report['release_fingerprint'])


def test_release_cannot_copy_credentials_or_runtime_data(prepared):
    _,_,_,root,_=prepared;(root/'.env.local').write_text('SECRET=value')
    with pytest.raises(ValueError,match='Environment files'):prepare(prepared)


def test_local_gates_block_model_calls_and_release_creation(prepared,monkeypatch):
    _,store,job,_,agents=prepared
    def blocked(*_):raise ValueError('Current security evidence is missing')
    monkeypatch.setattr(release,'release_gate',blocked)
    with pytest.raises(ValueError,match='security'):prepare(prepared)
    assert not agents.calls
    assert not any(e['status']=='RELEASE_REVIEW' for e in store.read(job)['events'])


def test_publish_requires_approval_and_cannot_target_controller_repo(prepared,monkeypatch):
    _,store,job,_,_=prepared;report,_=prepare(prepared)
    with pytest.raises(ValueError,match='approval'):release.publish_release(job,store,report['release_fingerprint'])
    monkeypatch.setattr(release,'gh',lambda *_:'somebody-else')
    with pytest.raises(ValueError,match='personal account'):release.publish_release(job,store,report['release_fingerprint'],True)


def published(prepared,monkeypatch,database='none'):
    _,store,job,_,_=prepared;report,_=prepare(prepared,database)
    sha='a'*40
    store.event(job,'APP_PUBLISHED',{'repository':'person/generated-app','sha':sha,'release_fingerprint':report['release_fingerprint']},update_status=False)
    calls=[]
    def gh(*args):
        calls.append(args)
        if args[0]=='api':return json.dumps({'sha':sha})
        if args[0]=='run':return json.dumps([{'headSha':sha,'event':'push','status':'completed','conclusion':'success','databaseId':1,'url':'https://github.com/person/generated-app/actions/runs/1'}])
        if args[0]=='secret':return json.dumps([{'name':name} for name in release.SECRETS])
        return ''
    monkeypatch.setattr(release,'gh',gh)
    return report,sha,calls


def test_deployment_dispatch_requires_exact_commit_ci_secrets_and_separate_approval(prepared,monkeypatch):
    _,store,job,_,_=prepared;report,sha,calls=published(prepared,monkeypatch)
    with pytest.raises(ValueError,match='approval'):release.deploy_release(job,store,report['release_fingerprint'])
    release.deploy_release(job,store,report['release_fingerprint'],True)
    dispatch=[call for call in calls if call[:2]==('workflow','run')]
    assert len(dispatch)==1 and f'approved_sha={sha}' in dispatch[0]
    assert not any(e['status']=='APP_DEPLOYMENT_STATUS' for e in store.read(job)['events'])
    with pytest.raises(ValueError,match='already dispatched'):release.deploy_release(job,store,report['release_fingerprint'],True)


@pytest.mark.parametrize('block',['sqlite','ci','secrets','remote'])
def test_deployment_blockers_never_dispatch(prepared,monkeypatch,block):
    _,store,job,_,_=prepared
    report,sha,calls=published(prepared,monkeypatch,'sqlite' if block=='sqlite' else 'none')
    original=release.gh
    def gh(*args):
        if block=='ci' and args[0]=='run':return json.dumps([{'headSha':sha,'event':'push','status':'completed','conclusion':'failure'}])
        if block=='secrets' and args[0]=='secret':return '[]'
        if block=='remote' and args[0]=='api':return json.dumps({'sha':'b'*40})
        return original(*args)
    monkeypatch.setattr(release,'gh',gh)
    with pytest.raises(ValueError):release.deploy_release(job,store,report['release_fingerprint'],True)
    assert not any(call[:2]==('workflow','run') for call in calls)


def test_newer_pending_ci_supersedes_older_success(prepared,monkeypatch):
    _,store,job,_,_=prepared;report,sha,calls=published(prepared,monkeypatch)
    original=release.gh
    def gh(*args):
        if args[0]=='run':return json.dumps([{'headSha':sha,'event':'push','status':'in_progress','conclusion':''},
                                            {'headSha':sha,'event':'push','status':'completed','conclusion':'success'}])
        return original(*args)
    monkeypatch.setattr(release,'gh',gh)
    with pytest.raises(ValueError,match='CI must pass'):release.deploy_release(job,store,report['release_fingerprint'],True)
    assert not any(call[:2]==('workflow','run') for call in calls)


def test_publish_creates_only_reviewed_private_app_repo_once(prepared,monkeypatch):
    _,store,job,root,_=prepared;report,bundle=prepare(prepared);calls=[]
    def gh(*args):
        calls.append(args)
        return 'person' if args[0]=='api' else ''
    git=[]
    def command(args,cwd=None):
        git.append(args)
        return 'a'*40 if args[:2]==['git','rev-parse'] else ''
    monkeypatch.setattr(release,'gh',gh);monkeypatch.setattr(release,'command',command)
    release.publish_release(job,store,report['release_fingerprint'],True)
    assert ('repo','create','person/generated-app','--private','--description','Application generated and verified by ForgeFSD') in calls
    assert any(args[:2]==['git','push'] and '--force' not in args for args in git)
    assert store.read(job)['events'][-1]['status']=='APP_PUBLISHED'
    assert source_fingerprint(bundle)==report['bundle_fingerprint']
    with pytest.raises(ValueError,match='already attempted'):release.publish_release(job,store,report['release_fingerprint'],True)


def test_successful_deploy_workflow_requires_matching_url_artifact(prepared,monkeypatch):
    project,store,job,_,_=prepared;report,sha,calls=published(prepared,monkeypatch)
    release.deploy_release(job,store,report['release_fingerprint'],True)
    original=release.gh
    def gh(*args):
        if args[0]=='run' and '--workflow' in args and args[args.index('--workflow')+1]=='deploy.yml':
            return json.dumps([{'databaseId':5,'headSha':sha,'event':'workflow_dispatch','displayTitle':'Deploy '+sha,
                               'createdAt':'2099-01-01T00:00:00Z','status':'completed','conclusion':'success'}])
        if args[:2]==('run','download'):
            directory=Path(args[-1]);directory.mkdir(parents=True)
            (directory/'deployment.json').write_text(json.dumps({'sha':sha,'url':'https://demo.vercel.app'}))
            return ''
        return original(*args)
    monkeypatch.setattr(release,'gh',gh)
    release.refresh_release(job,store,report['release_fingerprint'])
    assert store.read(job)['events'][-1]['payload']['cloud_deployed'] is True
    result=project/'artifacts/releases'/job/'deployments/5/deployment.json'
    result.write_text(json.dumps({'sha':'b'*40,'url':'https://demo.vercel.app'}))
    with pytest.raises(ValueError,match='approved commit'):release.refresh_release(job,store,report['release_fingerprint'])


def test_cleanup_does_not_revive_a_historical_deployment(prepared,monkeypatch):
    _,store,job,_,_=prepared;report,_,calls=published(prepared,monkeypatch)
    store.event(job,'APP_DEPLOYMENT_REMOVED',{'release_fingerprint':report['release_fingerprint'],
                'project_id':'prj_test','evidence':'cleanup.json'},update_status=False)
    release.refresh_release(job,store,report['release_fingerprint'])
    result=store.read(job)['events'][-1]
    assert result['status']=='APP_DEPLOYMENT_STATUS'
    assert result['payload']['removed'] and not result['payload']['cloud_deployed']
    assert not any('--workflow' in args and args[args.index('--workflow')+1]=='deploy.yml' for args in calls)
