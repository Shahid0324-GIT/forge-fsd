import sys

import pytest

from forge.persistence import JobStore
from forge.repair import repair_job
from forge.verification import bounded_command


def test_execution_timeout_is_reported():
    result = bounded_command([sys.executable,'-c','import time; time.sleep(5)'],timeout=.2)
    assert result['stopped'] == 'timeout'
    assert result['exit_code'] != 0


def test_execution_output_is_bounded():
    result = bounded_command([sys.executable,'-c',"print('x'*100000)"],output_limit=1000)
    assert result['stopped'] == 'output_limit'
    assert len(result['output']) <= 1000


def test_repair_requires_real_failure(tmp_path):
    store = JobStore(tmp_path/'jobs.db')
    job = store.create()
    with pytest.raises(ValueError,match='verification failure'):
        repair_job(job,None,store)


def test_repair_budget_blocks_third_attempt(tmp_path):
    store = JobStore(tmp_path/'jobs.db')
    job = store.create()
    for i in range(2):
        store.event(job,'REPAIRING',{'attempt':i+1})
        store.event(job,'VERIFICATION_FAILED',{})
    with pytest.raises(ValueError,match='limit exhausted'):
        repair_job(job,None,store)


def test_second_attempt_restores_only_compiler_implicated_files(tmp_path, monkeypatch):
    import json
    import forge.repair as repair_module
    from forge.workspace import source_fingerprint
    monkeypatch.setattr(repair_module,'PROJECT',tmp_path)
    store=JobStore(tmp_path/'jobs.db'); job=store.create()
    root=tmp_path/'workspace'/job; (root/'lib').mkdir(parents=True)
    (root/'lib/db.ts').write_text('broken code')
    (root/'lib/tasks.ts').write_text('unchanged task implementation')
    reference=tmp_path/'templates/task-app/lib'; reference.mkdir(parents=True)
    (reference/'db.ts').write_text('trusted database adapter')
    report=tmp_path/'failure.json'
    report.write_text(json.dumps({'source_fingerprint':source_fingerprint(root),'checks':{'results':[{'exit_code':2,'name':'typecheck','output':'lib/db.ts(1,1): compiler error'}]}}))
    store.event(job,'REPAIRING',{'attempt':1})
    store.event(job,'VERIFICATION_FAILED',{'report':str(report)})
    class QA:
        def generate(self,*args,**kwargs):
            return {'diagnosis':'Invalid adapter API','recommendation':'Restore the implicated template file'}
    result=repair_module.repair_job(job,QA(),store)
    assert result['status']=='GENERATED_UNVERIFIED'
    assert (root/'lib/db.ts').read_text()=='trusted database adapter'
    assert (root/'lib/tasks.ts').read_text()=='unchanged task implementation'
