"""Durable, explicitly approved Claude spending allowance shared by a run's workers."""
import json
from uuid import uuid4

from forge.provider_errors import ProviderResourceError

MODEL='anthropic:claude-opus-5-5'


def authorize(store,job_id,*,approved=False,actor=''):
    if approved is not True or not actor:raise ValueError('Claude run budget needs explicit approval')
    from forge.models import job_model
    if job_model(store.read(job_id))!=MODEL:raise ValueError('Budget requires a Claude run')
    with store.connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS claude_budgets(job_id TEXT PRIMARY KEY,limit_micro INTEGER NOT NULL,actor TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS claude_spend(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,reserved_micro INTEGER NOT NULL,charged_micro INTEGER,status TEXT NOT NULL,usage TEXT);''')
        db.execute('INSERT INTO claude_budgets VALUES (?,?,?)',(job_id,3_000_000,actor))
    store.event(job_id,'PROVIDER_BUDGET_APPROVED',{'model':MODEL,'limit_usd':3,'actor':actor,
        'scope':'Application-side allowance, shared across workers/restarts. Uncertain requests retain their full reservation; taxes are excluded.'},update_status=False)


class RunBudget:
    def __init__(self,store,job_id):self.store=store;self.job_id=job_id

    @classmethod
    def for_job(cls,store,job_id):
        with store.connect() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='claude_budgets'").fetchone():return None
            if not db.execute('SELECT 1 FROM claude_budgets WHERE job_id=?',(job_id,)).fetchone():return None
        return cls(store,job_id)

    def reserve(self,payload):
        # UTF-8 bytes conservatively bound text tokens, plus protocol overhead.
        # Reserve input at $8/M (also covers cache writes), output at $20/M.
        upper=(len(json.dumps(payload).encode())+8192)*8+payload['max_tokens']*20
        identifier=uuid4().hex
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cap=db.execute('SELECT limit_micro FROM claude_budgets WHERE job_id=?',(self.job_id,)).fetchone()[0]
            used=db.execute('SELECT COALESCE(SUM(COALESCE(charged_micro,reserved_micro)),0) FROM claude_spend WHERE job_id=?',(self.job_id,)).fetchone()[0]
            if used+upper>cap:raise ProviderResourceError('Claude run budget cannot cover another request reservation. Saved work retained; no API request sent.')
            db.execute('INSERT INTO claude_spend VALUES (?,?,?,?,?,?)',(identifier,self.job_id,upper,None,'reserved',None))
        return identifier

    def settle(self,identifier,usage):
        fields=['input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens']
        if not isinstance(usage,dict) or not all(type(usage.get(k,0)) is int and usage.get(k,0)>=0 for k in fields):
            raise ProviderResourceError('Claude usage was invalid; full request reservation retained')
        if 'input_tokens' not in usage or 'output_tokens' not in usage:raise ProviderResourceError('Claude usage missing; full request reservation retained')
        cost=usage['input_tokens']*4+usage['output_tokens']*20+usage.get('cache_creation_input_tokens',0)*8+usage.get('cache_read_input_tokens',0)*4
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT reserved_micro,status FROM claude_spend WHERE id=? AND job_id=?',(identifier,self.job_id)).fetchone()
            if not row or row[1]!='reserved':raise ValueError('Claude reservation already settled or belongs to another run')
            db.execute('UPDATE claude_spend SET charged_micro=?,status=?,usage=? WHERE id=?',(cost,'settled',json.dumps(usage),identifier))
        if cost>row[0]:raise ProviderResourceError('Claude usage exceeded its conservative reservation; inspect billing before continuing')

    def summary(self):
        with self.store.connect() as db:
            count,cost=db.execute('SELECT COUNT(*),COALESCE(SUM(COALESCE(charged_micro,reserved_micro)),0) FROM claude_spend WHERE job_id=?',(self.job_id,)).fetchone()
        return {'requests_used':count,'run_budget_usd':3,'charged_or_reserved_usd':cost/1_000_000}
