import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4

from forge.builders import PROJECT


class BusyError(ValueError):pass


class OperationManager:
    def __init__(self,store, *, spawn=None):
        self.store=store;self.lock=threading.RLock();self.processes={};self.closed=False
        self._spawn=spawn or subprocess.Popen
        with store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL, request_id TEXT NOT NULL,
                action TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
                finished_at TEXT, reason TEXT, UNIQUE(job_id,request_id));
                CREATE UNIQUE INDEX IF NOT EXISTS one_dashboard_worker ON operations(status) WHERE status='RUNNING';''')
            old=db.execute("SELECT id,job_id FROM operations WHERE status='RUNNING'").fetchall()
            db.execute("UPDATE operations SET status='INTERRUPTED',reason='Dashboard restarted; worker ownership lost' WHERE status='RUNNING'")
        for _,job in old:
            store.event(job,'INTERRUPTED',{'reason':'Dashboard restarted during an operation; inspect before retrying'})

    def read(self,operation_id):
        with self.store.connect() as db:
            db.row_factory=__import__('sqlite3').Row
            row=db.execute('SELECT * FROM operations WHERE id=?',(operation_id,)).fetchone()
        return dict(row) if row else None

    def active(self,job_id=None):
        with self.store.connect() as db:
            db.row_factory=__import__('sqlite3').Row
            query="SELECT * FROM operations WHERE status='RUNNING'"
            rows=db.execute(query+(' AND job_id=?' if job_id else ''),(job_id,) if job_id else ()).fetchall()
        return [dict(row) for row in rows]

    def submit(self,job_id,action,payload,request_id,expected_sequence):
        with self.lock:
            if self.closed:raise BusyError('Dashboard is shutting down')
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                existing=db.execute('SELECT id FROM operations WHERE job_id=? AND request_id=?',(job_id,request_id)).fetchone()
                if existing:return self.read(existing[0])
                if db.execute("SELECT 1 FROM operations WHERE status='RUNNING'").fetchone():raise BusyError('Another operation is running. Wait or stop it first.')
                latest=db.execute('SELECT MAX(sequence) FROM events WHERE job_id=?',(job_id,)).fetchone()[0]
                if latest!=expected_sequence:raise BusyError('This view is out of date. Refresh and review the latest state.')
                operation_id=uuid4().hex
                db.execute('INSERT INTO operations(id,job_id,request_id,action,status,started_at) VALUES (?,?,?,?,?,?)',
                           (operation_id,job_id,request_id,action,'RUNNING',datetime.now(timezone.utc).isoformat()))
            directory=PROJECT/'artifacts/operations'/operation_id;directory.mkdir(parents=True)
            config=directory/'input.json';config.write_text(json.dumps({'db':str(self.store.path.resolve()),'job_id':job_id,'action':action,'payload':payload}),encoding='utf-8')
            self.store.event(job_id,'OPERATION_STARTED',{'operation_id':operation_id,'action':action},update_status=False)
            try:
                output=open(directory/'worker.log','wb')
                process=self._spawn([sys.executable,'-m','forge.dashboard_worker',str(config)],cwd=PROJECT,stdout=output,stderr=subprocess.STDOUT,
                                         creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                self.processes[operation_id]=process
                threading.Thread(target=self._watch,args=(operation_id,job_id,process,output,directory/'worker.log'),daemon=True).start()
            except Exception as exc:
                if 'output' in locals():output.close()
                self._finish(operation_id,job_id,'FAILED',str(exc));raise
            return self.read(operation_id)

    def _finish(self,operation_id,job_id,status,reason=None):
        with self.store.connect() as db:
            updated=db.execute("UPDATE operations SET status=?,finished_at=?,reason=? WHERE id=? AND status='RUNNING'",
                (status,datetime.now(timezone.utc).isoformat(),reason,operation_id)).rowcount
        if updated:self.store.event(job_id,'OPERATION_FINISHED',{'operation_id':operation_id,'outcome':status,'reason':reason},update_status=False)

    def _terminate(self,process):
        if process.poll() is not None:return
        if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
        else:process.kill()
        process.wait(timeout=15)

    def _watch(self,operation_id,job_id,process,output,log):
        started=time.monotonic();reason=None
        try:
            while process.poll() is None:
                if time.monotonic()-started>1800:reason='Operation exceeded 30-minute budget'
                if log.exists() and log.stat().st_size>2_000_000:reason='Operation log exceeded output budget'
                if reason:self._terminate(process);break
                time.sleep(.2)
            status='SUCCEEDED' if process.returncode==0 and not reason else 'FAILED'
            if reason:self.cleanup_job(job_id);self.store.event(job_id,'FAILED',{'reason':reason})
            in_progress={'RECEIVED','REQUIREMENTS','PLANNING','TEST_PLANNING','BUILDING','VERIFYING','REPAIRING','SECURITY_CHECK','PREVIEW_STARTING','AUTONOMOUS_BUILDING','AUTONOMOUS_REPLANNING'}
            if status=='FAILED' and self.read(operation_id)['status']=='RUNNING' and self.store.read(job_id)['status'] in in_progress:
                try:self.cleanup_job(job_id)
                except Exception:pass
                self.store.event(job_id,'FAILED',{'reason':reason or 'The worker stopped unexpectedly. Review its saved activity before retrying.'})
            self._finish(operation_id,job_id,status,reason or ('This operation encountered errors. Review the saved activity and reports.' if status=='FAILED' else None))
        except Exception as exc:
            self._finish(operation_id,job_id,'FAILED',str(exc)[:1000])
        finally:
            output.close()
            with self.lock:self.processes.pop(operation_id,None)

    def cleanup_job(self,job_id):
        from forge.browser_testing import cleanup_browser
        from forge.preview import cleanup,preview_resources
        record=self.store.read(job_id)
        if record['status']=='REQUEST_ANSWERED':return
        browser=next((e['payload']['resources'] for e in reversed(record['events']) if e['status']=='AUTOMATED_BROWSER_STARTED'),None)
        if browser:cleanup_browser(browser,job_id)
        resources=preview_resources(record)
        if resources:cleanup(resources,job_id)
        ids=subprocess.run(['docker','ps','-aq','--filter',f'label=forge.job={job_id}'],capture_output=True,text=True,timeout=15)
        if ids.returncode==0:
            for container_id in ids.stdout.split():
                info=json.loads(subprocess.check_output(['docker','inspect',container_id],text=True,timeout=15))[0]
                labels=info['Config'].get('Labels',{})
                if labels.get('forge.job')==job_id and labels.get('forge.role') in {'verification','scanner','audit','browser_verification'}:
                    subprocess.run(['docker','rm','--force',container_id],capture_output=True,timeout=20)

    def cancel(self,job_id):
        with self.lock:
            active=self.active(job_id)
            for operation in active:
                self._finish(operation['id'],job_id,'CANCELLED','Stopped by the local dashboard user')
                process=self.processes.get(operation['id'])
                if process:self._terminate(process)
            warning=None
            try:self.cleanup_job(job_id)
            except Exception as exc:warning=str(exc)[:1000]
            self.store.event(job_id,'CANCELLED',{'actor':'local_dashboard','note':'Local worker stopped. Ollama may finish an already submitted inference call.','cleanup_warning':warning})
        return self.store.read(job_id)

    def close(self):
        with self.lock:
            self.closed=True
            for operation in self.active():self.cancel(operation['job_id'])
            for job in self.store.list_jobs(limit=100):
                if job['status'] in {'PREVIEW_RUNNING','PREVIEW_STARTING'}:
                    try:
                        self.cleanup_job(job['job_id'])
                        self.store.event(job['job_id'],'PREVIEW_STOPPED',{'reason':'Dashboard shut down'})
                    except Exception as exc:
                        self.store.event(job['job_id'],'CLEANUP_WARNING',{'reason':str(exc)[:1000]},update_status=False)

    def delete(self,job_id):
        with self.lock:
            try:record=self.store.read(job_id)
            except KeyError:
                archived=self.store.read(job_id,include_deleted=True)
                if archived['deleted_at']:return {'job_id':job_id,'deleted':True,'recoverable':True}
                raise
            original=record['status']
            active=self.active(job_id)
            if active:
                cancelled=self.cancel(job_id)
                warning=cancelled['events'][-1]['payload'].get('cleanup_warning')
                if warning:raise BusyError('Work stopped, but cleanup needs attention before deleting: '+warning)
            else:self.cleanup_job(job_id)
            running={'RECEIVED','REQUIREMENTS','REQUIREMENTS_READY','CLARIFICATION_ANSWERED','PLANNING','BUILDING','VERIFYING','REPAIRING','SECURITY_CHECK','AUTONOMOUS_BUILDING','AUTONOMOUS_REPLANNING'}
            preview_stopped=original in {'PREVIEW_RUNNING','PREVIEW_STARTING'} or any(op['action'].startswith('preview_') for op in active)
            restored='PREVIEW_STOPPED' if preview_stopped else 'INTERRUPTED' if active or original in running else original
            self.store.event(job_id,'RUN_DELETED',{'actor':'local_dashboard','recoverable':True},update_status=False)
            self.store.trash(job_id,restored)
            return {'job_id':job_id,'deleted':True,'recoverable':True}
