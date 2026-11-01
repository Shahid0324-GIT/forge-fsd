import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now():
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL, timestamp TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL);
            """)
            columns={row[1] for row in db.execute('PRAGMA table_info(jobs)')}
            if 'deleted_at' not in columns:db.execute('ALTER TABLE jobs ADD COLUMN deleted_at TEXT')
            if 'restore_status' not in columns:db.execute('ALTER TABLE jobs ADD COLUMN restore_status TEXT')

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    @contextmanager
    def checkpoints(self):
        from langgraph.checkpoint.sqlite import SqliteSaver
        with SqliteSaver.from_conn_string(str(self.path.with_suffix(".checkpoints.sqlite3"))) as saver:
            yield saver

    def create(self, request=None):
        job_id = uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO jobs(id,status,created_at) VALUES (?, ?, ?)", (job_id, "RECEIVED", now()))
        self.event(job_id, "RECEIVED", request or {})
        return job_id

    def event(self, job_id, status, payload, *, update_status=True):
        with self.connect() as db:
            exists=db.execute("SELECT 1 FROM jobs WHERE id=? AND deleted_at IS NULL",(job_id,)).fetchone()
            if not exists:
                raise KeyError(job_id)
            if update_status:
                db.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
            db.execute("INSERT INTO events(job_id,timestamp,status,payload) VALUES (?,?,?,?)",
                       (job_id, now(), status, json.dumps(payload)))

    def read(self, job_id, *, include_deleted=False):
        with self.connect() as db:
            row = db.execute("SELECT status,created_at,deleted_at FROM jobs WHERE id=?" + ('' if include_deleted else ' AND deleted_at IS NULL'), (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            events = db.execute("SELECT sequence,timestamp,status,payload FROM events WHERE job_id=? ORDER BY sequence", (job_id,)).fetchall()
        return {"job_id": job_id, "status": row[0], "created_at": row[1], "deleted_at":row[2],
                "events": [{"sequence": n, "timestamp": t, "status": s, "payload": json.loads(p)} for n, t, s, p in events]}

    def list_jobs(self, limit=30, *, deleted=False):
        with self.connect() as db:
            ids=db.execute('SELECT id FROM jobs WHERE deleted_at IS '+('NOT NULL' if deleted else 'NULL')+' ORDER BY created_at DESC LIMIT ?', (limit,)).fetchall()
        return [self.read(row[0],include_deleted=deleted) for row in ids]

    def trash(self,job_id,restore_status):
        with self.connect() as db:
            if db.execute('UPDATE jobs SET deleted_at=?,restore_status=? WHERE id=? AND deleted_at IS NULL',(now(),restore_status,job_id)).rowcount!=1:
                raise KeyError(job_id)

    def restore(self,job_id):
        with self.connect() as db:
            if db.execute('UPDATE jobs SET status=restore_status,restore_status=NULL,deleted_at=NULL WHERE id=? AND deleted_at IS NOT NULL',(job_id,)).rowcount!=1:
                raise KeyError(job_id)
        self.event(job_id,'RUN_RESTORED',{'actor':'local_dashboard'},update_status=False)
        return self.read(job_id)

    def events_after(self, job_id, cursor, limit=100):
        with self.connect() as db:
            rows=db.execute('SELECT sequence,timestamp,status,payload FROM events WHERE job_id=? AND sequence>? ORDER BY sequence LIMIT ?', (job_id,cursor,limit)).fetchall()
        return [{'sequence':n,'timestamp':t,'status':s,'payload':json.loads(p)} for n,t,s,p in rows]
