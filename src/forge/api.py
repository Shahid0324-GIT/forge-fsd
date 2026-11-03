import asyncio
import hashlib
import io
import json
import re
import secrets
import threading
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import Field, StrictBool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from forge.builders import PROJECT,build_retryable
from forge.operations import BusyError,OperationManager
from forge.persistence import JobStore
from forge.schemas import ApplicationRequest,Boundary
from forge.workspace import safe_path,source_fingerprint
from forge.workflow import planning_retryable
from forge.browser_testing import profile_for,browser_gate
from forge.autonomous_planning import uses_autonomous_planning,resumable_planning,AppDraft
from forge.autonomous_review import review_snapshot
from forge.autonomous_build import build_resumable
from forge.autonomous_testing import tests_resumable,evidence_current
from forge.groq_model import GROQ_MODEL,groq_configured


class NewJob(ApplicationRequest):
    request_id: str = Field(pattern=r'^[a-f0-9-]{32,36}$')
    workflow: Literal['typed','autonomous'] = 'typed'


class Action(Boundary):
    action: Literal['answer','approve','reject','continue','preview_start','preview_stop','preview_status','report','security','retry_plan','retry_build','browser_check','prepare_release','publish_release','deploy_release','release_status','resume_planning','revise_plan','resume_build','test_app','resume_tests','retry_coverage']
    request_id: str = Field(pattern=r'^[a-f0-9-]{32,36}$')
    expected_sequence: int = Field(ge=1)
    fingerprint: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')
    answers: list[str] | None = Field(default=None,min_length=1,max_length=3)
    approved: StrictBool = False
    repository: str | None = Field(default=None,max_length=140)
    feedback: str | None = Field(default=None,min_length=1,max_length=2000)


ALLOWED={
    **{action:{'SECURITY_PASSED','PREVIEW_RUNNING','PREVIEW_STOPPED','PREVIEW_FAILED'} for action in ['prepare_release','publish_release','deploy_release','release_status']},
    'browser_check':{'FUNCTIONALLY_VERIFIED','SECURITY_PASSED','PREVIEW_RUNNING','PREVIEW_STOPPED','PREVIEW_FAILED'},
    'retry_build':{'FAILED'},
    'retry_plan':{'FAILED'},
    'answer':{'AWAITING_CLARIFICATION','AUTONOMOUS_INPUT_NEEDED'},'approve':{'PLAN_REVIEW','AUTONOMOUS_DRAFT_READY'},'reject':{'PLAN_REVIEW','AUTONOMOUS_DRAFT_READY'},
    'resume_planning':{'AUTONOMOUS_PAUSED'},
    'revise_plan':{'AUTONOMOUS_DRAFT_READY'},'resume_build':{'AUTONOMOUS_BUILD_PAUSED'},
    'test_app':{'AUTONOMOUS_BUILD_CHECKS_PASSED'},'resume_tests':{'AUTONOMOUS_TEST_PAUSED'},
    'retry_coverage':{'AUTONOMOUS_CHECKS_BLOCKED'},
    'continue':{'APPROVED','GENERATED_UNVERIFIED','VERIFICATION_FAILED','FUNCTIONALLY_VERIFIED','SECURITY_BLOCKED','SECURITY_PASSED','AUTONOMOUS_APPROVED'},
    'preview_start':{'SECURITY_PASSED','PREVIEW_STOPPED','PREVIEW_FAILED'},
    'preview_stop':{'PREVIEW_RUNNING','PREVIEW_STARTING','PREVIEW_FAILED'},
    'preview_status':{'PREVIEW_RUNNING','PREVIEW_STARTING','PREVIEW_STOPPED'},
    'report':{'SECURITY_PASSED','PREVIEW_RUNNING','PREVIEW_STOPPED'},
    'security':{'SECURITY_PASSED','SECURITY_BLOCKED','FUNCTIONALLY_VERIFIED','PREVIEW_STOPPED','PREVIEW_FAILED'},
}


def create_app(db_path=None, *, manager_factory=OperationManager):
    store=JobStore(Path(db_path) if db_path else PROJECT/'artifacts/jobs.sqlite3')
    manager=manager_factory(store)
    cookie=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        yield
        manager.close()

    app=FastAPI(title='ForgeFSD Local Control Plane',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store;app.state.operations=manager
    app.state.shutting_down=False
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost'])

    @app.middleware('http')
    async def local_session(request,call_next):
        host=request.headers.get('host','')
        if host.split(':')[0] not in {'127.0.0.1','localhost'}:
            return JSONResponse({'detail':'Only local dashboard hosts are accepted'},status_code=403)
        origin=request.headers.get('origin')
        expected=f'{request.url.scheme}://{host}'
        if origin and origin!=expected:
            return JSONResponse({'detail':'Cross-origin dashboard access is forbidden'},status_code=403)
        if request.url.path.startswith('/api/') and request.url.path!='/api/session':
            if app.state.shutting_down:
                return JSONResponse({'detail':'The workspace is shutting down'},status_code=503)
            if not secrets.compare_digest(request.cookies.get('forge_session',''),cookie):
                return JSONResponse({'detail':'Open the local dashboard to establish a session'},status_code=401)
            if request.method not in {'GET','HEAD','OPTIONS'}:
                if not secrets.compare_digest(request.headers.get('x-forge-csrf',''),csrf):
                    return JSONResponse({'detail':'Missing or invalid action token'},status_code=403)
                body=bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body)>16000:return JSONResponse({'detail':'Request exceeds the input budget'},status_code=413)
                request._body=bytes(body)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-ForgeFSD-Control-Plane']='1'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers['Cache-Control']='no-store' if request.url.path.startswith('/api/') else 'no-cache'
        return response

    def record(job_id):
        if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise HTTPException(400,'Invalid job identity')
        try:return store.read(job_id)
        except KeyError:raise HTTPException(404,'Job not found')

    def view(job):
        job={**job}
        job['active_operation']=next(iter(manager.active(job['job_id'])),None)
        job['workflow']='autonomous' if uses_autonomous_planning(job) else 'typed'
        job['planning_resumable']=resumable_planning(job,store)
        job['build_resumable']=build_resumable(job,store,workspace_boundary=PROJECT/'workspace')
        job['tests_resumable']=tests_resumable(job,store,workspace_boundary=PROJECT/'workspace')
        if job['status']=='AUTONOMOUS_APP_CHECKS_PASSED':job['app_evidence_current']=evidence_current(job,store,workspace_boundary=PROJECT/'workspace')
        if job['workflow']=='autonomous' and job['status']=='AUTONOMOUS_DRAFT_READY':
            try:job['review_fingerprint']=review_snapshot(job['job_id'],store)['fingerprint']
            except (ValueError,OSError,KeyError) as exc:job['review_error']=str(exc)
        if job['status']=='AUTONOMOUS_BUILD_CHECKS_PASSED':
            passed=next(e['payload'] for e in reversed(job['events']) if e['status']=='AUTONOMOUS_BUILD_CHECKS_PASSED')
            try:job['build_evidence_current']=(PROJECT/'workspace'/job['job_id']).is_dir() and source_fingerprint(PROJECT/'workspace'/job['job_id'])==passed['source_fingerprint']
            except (ValueError,OSError):job['build_evidence_current']=False
        job['last_sequence']=job['events'][-1]['sequence'] if job['events'] else 0
        job['generation_retryable']=build_retryable(job)
        job['browser_profile']=profile_for(job)
        latest_source=next((e['payload'].get('source_fingerprint') for e in reversed(job['events']) if e['status']=='FUNCTIONALLY_VERIFIED'),None)
        job['browser_checks_blocked']=bool(latest_source and not browser_gate(job,latest_source))
        job['title']=next((e['payload']['title'] for e in reversed(job['events']) if e['status'] in {'REQUIREMENTS_READY','AUTONOMOUS_DRAFT_READY'}),'New application')
        if job['status']=='REQUEST_ANSWERED':job['title']='Request response'
        if job['status']=='PLAN_REVIEW':
            review=next((e for e in reversed(job['events']) if e['status']=='PLAN_REVIEW'),None)
            if review and 'fingerprint' not in review['payload']:
                job['legacy']=True
            elif review:
                from forge.schemas import RequirementsDocument,ImplementationPlan
                try:
                    RequirementsDocument.model_validate(review['payload']['requirements'])
                    ImplementationPlan.model_validate(review['payload']['plan'])
                except (ValueError,KeyError):job['legacy']=True
        return job

    @app.get('/api/session')
    def session():
        response=JSONResponse({'csrf':csrf,'model':'qwen2.5-coder:3b','mode':'local','supported_app':'Small single-user apps (experimental)',
            'groq_configured':groq_configured()})
        response.set_cookie('forge_session',cookie,httponly=True,samesite='strict',path='/')
        return response

    @app.post('/api/shutdown',status_code=202)
    def shutdown():
        callback=getattr(app.state,'request_shutdown',None)
        if callback is None:raise HTTPException(409,'This server was not started by the dashboard launcher')
        app.state.shutting_down=True
        threading.Timer(.3,callback).start()
        return {'status':'shutting_down'}

    @app.get('/api/jobs')
    def jobs():return {'jobs':[view(job) for job in store.list_jobs()], 'active_operations':manager.active()}

    @app.get('/api/trash')
    def trash():return {'jobs':[view(job) for job in store.list_jobs(limit=1000,deleted=True)]}

    @app.post('/api/jobs/{job_id}/delete')
    def delete_run(job_id:str):
        if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise HTTPException(400,'Invalid job identity')
        try:return manager.delete(job_id)
        except BusyError as exc:raise HTTPException(409,str(exc))
        except KeyError:raise HTTPException(404,'Run not found')
        except Exception as exc:raise HTTPException(409,'Could not finish stopping this run. It was not deleted. '+str(exc)[:500])

    @app.post('/api/jobs/{job_id}/restore')
    def restore_run(job_id:str):
        if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise HTTPException(400,'Invalid job identity')
        with manager.lock:
            try:return view(store.restore(job_id))
            except KeyError:raise HTTPException(404,'Deleted run not found')

    @app.get('/api/jobs/{job_id}')
    def job(job_id:str):
        with manager.lock:
            current=record(job_id)
            if current['status']=='PREVIEW_RUNNING' and not manager.active():
                from forge.preview import preview_status
                current=preview_status(job_id,store)
            return view(current)

    @app.post('/api/jobs',status_code=202)
    def new_job(body:NewJob):
        if body.model==GROQ_MODEL:
            if body.workflow!='autonomous':raise HTTPException(422,'Groq is enabled for the autonomous app workflow only')
            if not groq_configured():raise HTTPException(422,'Configure GROQ_API_KEY in .env.local, then refresh the dashboard')
        with manager.lock:
            with store.connect() as db:
                existing=db.execute('SELECT id,job_id,action FROM operations WHERE request_id=?',(body.request_id,)).fetchone()
            if existing:
                if existing[2]!='plan':raise HTTPException(409,'Request identity already used for another action')
                try:previous=store.read(existing[1])
                except KeyError:raise HTTPException(409,'This request belongs to a deleted run. Start a new request or restore it from Trash.')
                if ('autonomous' if uses_autonomous_planning(previous) else 'typed')!=body.workflow:
                    raise HTTPException(409,'Request identity already belongs to a different workflow')
                return {'job_id':existing[1],'operation':manager.read(existing[0])}
            if manager.active():raise HTTPException(409,'Another operation is running. Wait or stop it first.')
            request=ApplicationRequest(description=body.description,model=body.model)
            job_id=store.create({**request.model_dump(),'workflow':body.workflow});latest=store.read(job_id)['events'][-1]['sequence']
            operation=manager.submit(job_id,'plan',request.model_dump(),body.request_id,latest)
            return {'job_id':job_id,'operation':operation}

    @app.post('/api/jobs/{job_id}/actions',status_code=202)
    def action(job_id:str,body:Action):
        current=record(job_id)
        with store.connect() as db:
            existing=db.execute('SELECT id,action FROM operations WHERE job_id=? AND request_id=?',(job_id,body.request_id)).fetchone()
        if existing:
            if existing[1]!=body.action:raise HTTPException(409,'Request identity already used for another action')
            return {'operation':manager.read(existing[0])}
        if current['status'] not in ALLOWED[body.action]:raise HTTPException(409,'That action is unavailable in the current job state')
        autonomous=uses_autonomous_planning(current)
        if autonomous and body.action not in {'answer','resume_planning','approve','reject','revise_plan','continue','resume_build','test_app','resume_tests','retry_coverage'}:
            raise HTTPException(409,'This workflow does not yet support preview or publishing')
        if body.action=='resume_planning' and not resumable_planning(current,store):
            raise HTTPException(409,'Planning needs saved-task inspection before it can resume')
        if body.action=='resume_build' and not build_resumable(current,store,workspace_boundary=PROJECT/'workspace'):
            raise HTTPException(409,'Inspect the interrupted build and approval before resuming')
        if body.action=='resume_tests' and not tests_resumable(current,store,workspace_boundary=PROJECT/'workspace'):
            raise HTTPException(409,'Inspect the interrupted QA work and frozen assertions before resuming')
        if body.action=='retry_plan' and not planning_retryable(current):raise HTTPException(409,'Only failed pre-review planning can be retried')
        if body.action=='retry_build' and not build_retryable(current):raise HTTPException(409,'Only an interrupted approved generation can be resumed once')
        if body.action=='browser_check' and not profile_for(current):raise HTTPException(409,'This app has no trusted automated browser profile')
        payload={}
        if body.action=='prepare_release':
            from forge.releases import validate_repository
            try:payload['repository']=validate_repository(body.repository or '')
            except ValueError as exc:raise HTTPException(422,str(exc))
        if body.action in {'publish_release','deploy_release','release_status'}:
            if not body.fingerprint:raise HTTPException(422,'Review the current release first')
            payload['fingerprint']=body.fingerprint
            if body.action!='release_status':
                if not body.approved:raise HTTPException(422,'Publishing and deployment each need explicit approval')
                payload['approved']=True
        if autonomous and body.action in {'approve','reject','revise_plan'}:
            try:review=review_snapshot(job_id,store)
            except (ValueError,OSError,KeyError) as exc:raise HTTPException(409,str(exc))
            if body.fingerprint!=review['fingerprint']:raise HTTPException(409,'Load and review the current proposal before deciding')
            payload['fingerprint']=body.fingerprint
            if body.action=='approve':
                if not body.approved:raise HTTPException(422,'Approve source generation and isolated build checks explicitly')
                payload['approved']=True
            if body.action=='revise_plan':
                if not body.feedback or not body.feedback.strip():raise HTTPException(422,'Describe the requested changes')
                payload['feedback']=body.feedback.strip()
        if not autonomous and body.action in {'approve','reject'}:
            review=next(e['payload'] for e in reversed(current['events']) if e['status']=='PLAN_REVIEW')
            if not body.fingerprint or body.fingerprint!=review.get('fingerprint'):
                raise HTTPException(409,'Review the current requirements and plan before deciding')
            payload['fingerprint']=body.fingerprint
        if body.action=='answer':
            question_status='AUTONOMOUS_INPUT_NEEDED' if uses_autonomous_planning(current) else 'AWAITING_CLARIFICATION'
            questions=next(e['payload']['questions'] for e in reversed(current['events']) if e['status']==question_status)
            if not body.answers or len(body.answers)!=len(questions) or any(not a.strip() or len(a)>1000 for a in body.answers):
                raise HTTPException(422,'Provide one nonempty answer per question, at most 1000 characters each')
            payload['answers']=body.answers
        if body.action=='preview_start':
            if not body.approved:raise HTTPException(422,'Preview needs explicit approval')
            payload['approved']=True
        try:operation=manager.submit(job_id,body.action,payload,body.request_id,body.expected_sequence)
        except BusyError as exc:raise HTTPException(409,str(exc))
        return {'operation':operation}

    @app.post('/api/jobs/{job_id}/cancel')
    def cancel(job_id:str):
        record(job_id)
        return view(manager.cancel(job_id))

    @app.get('/api/jobs/{job_id}/events')
    async def events(job_id:str,request:Request,after:int=0):
        record(job_id)
        try:cursor=max(after,int(request.headers.get('last-event-id','0')))
        except ValueError:raise HTTPException(422,'Invalid event cursor')
        async def stream():
            nonlocal cursor
            for _ in range(120):
                if app.state.shutting_down or await request.is_disconnected():break
                try:store.read(job_id)
                except KeyError:
                    yield 'event: deleted\ndata: {}\n\n'
                    break
                batch=store.events_after(job_id,cursor)
                for event in batch:
                    cursor=event['sequence']
                    yield f'id: {cursor}\nevent: workflow\ndata: {json.dumps(event)}\n\n'
                if not batch:yield ': heartbeat\n\n'
                await asyncio.sleep(.5)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})

    @app.get('/api/jobs/{job_id}/reports/{sequence}')
    def report(job_id:str,sequence:int):
        event=next((e for e in record(job_id)['events'] if e['sequence']==sequence),None)
        if not event or 'report' not in event['payload']:raise HTTPException(404,'Report not found')
        path=Path(event['payload']['report']).resolve()
        if not path.is_relative_to((PROJECT/'artifacts').resolve()) or path.suffix!='.json':raise HTTPException(403,'Report outside the artifact boundary')
        if not path.is_file():raise HTTPException(404,'Report file is unavailable')
        if path.stat().st_size>2_000_000:raise HTTPException(413,'Report exceeds display budget')
        if event['status']=='AGENT_HANDOFF':
            from forge.handoffs import read_handoff
            try:return JSONResponse(read_handoff(path,event['payload']))
            except (ValueError,KeyError):raise HTTPException(409,'Saved handoff failed its context/identity check')
        raw=path.read_bytes()
        if event['status'] in {'AUTONOMOUS_ACCEPTANCE_FROZEN','AUTONOMOUS_APP_CHECKS_PASSED'}:
            expected=event['payload'].get('contract_fingerprint') if event['status']=='AUTONOMOUS_ACCEPTANCE_FROZEN' else event['payload'].get('report_sha256')
            if hashlib.sha256(raw).hexdigest()!=expected:raise HTTPException(409,'Saved app-check evidence changed; do not use it as a current result')
        if event['status']=='AUTONOMOUS_DRAFT_READY':
            if hashlib.sha256(raw).hexdigest()!=event['payload'].get('draft_sha256'):
                raise HTTPException(409,'The saved proposal changed; do not review stale evidence')
            try:
                result=AppDraft.model_validate_json(raw).model_dump()
                current=record(job_id)
                latest=next(e for e in reversed(current['events']) if e['status']=='AUTONOMOUS_DRAFT_READY')
                if current['status']=='AUTONOMOUS_DRAFT_READY' and latest['sequence']==event['sequence']:
                    review=review_snapshot(job_id,store)
                    result.update(review_fingerprint=review['fingerprint'],review_scope=review['binding']['scope'])
                return JSONResponse(result)
            except (ValueError,OSError,KeyError):raise HTTPException(409,'The saved proposal is no longer valid')
        return JSONResponse(json.loads(raw))

    @app.get('/api/jobs/{job_id}/source.zip')
    def source(job_id:str):
        record(job_id);root=PROJECT/'workspace'/job_id
        if manager.active(job_id):raise HTTPException(409,'Wait until the current operation finishes before downloading a source snapshot')
        if not root.is_dir():raise HTTPException(404,'No generated source yet')
        safe_path(root,'package.json');buffer=io.BytesIO();total=0
        with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in root.rglob('*'):
                relative=path.relative_to(root).as_posix()
                if any(part in {'node_modules','.next','data','.git'} for part in path.relative_to(root).parts):continue
                if path.name.startswith('.env') and path.name!='.env.example':continue
                if path.is_symlink() or path.is_junction():raise HTTPException(403,'Linked source files are not downloadable')
                if path.is_file():
                    safe_path(root,relative);total+=path.stat().st_size
                    if total>5_000_000:raise HTTPException(413,'Source archive exceeds budget')
                    archive.writestr(relative,path.read_bytes())
        return StreamingResponse(iter([buffer.getvalue()]),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="forge-app-{job_id[:8]}.zip"'})

    ui=PROJECT/'apps/web/dist'
    if ui.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount('/',StaticFiles(directory=ui,html=True),name='dashboard')
    else:
        @app.get('/')
        def missing_ui():return JSONResponse({'detail':'Build apps/web before opening the dashboard'},status_code=503)
    return app
