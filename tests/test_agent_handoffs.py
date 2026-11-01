import hashlib
import json
from pathlib import Path

import pytest

from forge.handoffs import record_handoff
from forge.persistence import JobStore
from forge.workspace import app_coding_context, source_fingerprint
from test_general_apps import calculator_plan, calculator_spec


def repair_fixture(tmp_path, monkeypatch):
    import forge.repair as module
    monkeypatch.setattr(module, 'PROJECT', tmp_path)
    store = JobStore(tmp_path / 'jobs.db')
    job = store.create()
    root = tmp_path / 'workspace' / job
    for file, content in {'lib/calculate.ts': 'export const version="before";',
                          'app/api/calculate/route.ts': 'export const route="before";',
                          'app/page.tsx': 'export default function Page(){return null;}'}.items():
        path = root / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')
    plan = calculator_plan()
    plan['tasks'][1]['files'].insert(0, 'lib/calculate.ts')
    store.event(job, 'PLAN_REVIEW', {'requirements': calculator_spec(), 'plan': plan})

    def fail():
        path = tmp_path / 'failure.json'
        path.write_text(json.dumps({'source_fingerprint': source_fingerprint(root), 'checks': {'results': [
            {'name': 'acceptance', 'exit_code': 1, 'output': 'Wrong total ' * 2000},
            {'name': 'typecheck', 'exit_code': 1, 'output': 'lib/calculate.ts: wrong signature'}]}}), encoding='utf-8')
        store.event(job, 'VERIFICATION_FAILED', {'report': str(path)})
    fail()
    return module, store, job, root, fail


def test_handoff_persists_exact_context_without_changing_status(tmp_path):
    store = JobStore(tmp_path / 'jobs.db')
    job = store.create()
    context = {'requirements': {'title': 'Café'}, 'existing_source': {'lib/a.ts': 'export const a=1;'}}
    payload = record_handoff(store, job, 'backend_builder', 'frontend_builder', 'Use this API.', context)
    context['requirements']['title'] = 'changed after sending'
    saved = json.loads(Path(payload['report']).read_text(encoding='utf-8'))['context']
    canonical = json.dumps(saved, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    assert saved['requirements']['title'] == 'Café'
    assert hashlib.sha256(canonical).hexdigest() == payload['context_sha256']
    assert payload['source_files'] == ['lib/a.ts']
    assert store.read(job)['status'] == 'RECEIVED'
    with pytest.raises(ValueError, match='budget'):
        record_handoff(store, job, 'a', 'b', 'Too large', {'value': 'x' * 160001})


def test_repair_refreshes_cross_file_context_and_retains_diagnosis_between_attempts(tmp_path, monkeypatch):
    module, store, job, root, fail = repair_fixture(tmp_path, monkeypatch)

    class Agents:
        rounds = 0
        def generate(self, schema, instruction, data, **kwargs):
            assert len(json.dumps(data, separators=(',', ':'))) <= 14000
            if schema.__name__ == 'AppRepairAnalysis':
                self.rounds += 1
                previous = data['repair']['previous_diagnosis']
                assert (previous is None) == (self.rounds == 1)
                if previous:assert previous['diagnosis'] == 'Helper and route disagree'
                assert [f['name'] for f in data['repair']['failures']] == ['acceptance', 'typecheck']
                assert sum(len(f['output']) for f in data['repair']['failures']) <= 3000
                return {'diagnosis': 'Helper and route disagree', 'recommendation': 'Align both interfaces',
                        'files': ['app/api/calculate/route.ts', 'lib/calculate.ts']}
            if data['file'] == 'lib/calculate.ts':
                return {'content': f'export const version="after-{self.rounds}";'}
            assert data['reference_only_source']['lib/calculate.ts'] == f'export const version="after-{self.rounds}";'
            assert data['current_source'].startswith('export const route=')
            assert data['file'] not in data['reference_only_source']
            assert data['repair']['current_source_fingerprint'] == source_fingerprint(root)
            return {'content': f'export const route="after-{self.rounds}";'}

    agents = Agents()
    for _ in range(2):
        result = module.repair_job(job, agents, store)
        assert result['status'] == 'GENERATED_UNVERIFIED'
        fail()
    with pytest.raises(ValueError, match='exhausted'):
        module.repair_job(job, agents, store)
    handoffs = [e['payload'] for e in store.read(job)['events'] if e['status'] == 'AGENT_HANDOFF']
    assert [(e['sender'], e['recipient']) for e in handoffs[:3]] == [
        ('verification', 'qa'), ('qa', 'backend_builder'), ('qa', 'backend_builder')]
    assert agents.rounds == 2


def test_repair_rejects_new_dependency_before_writing_file(tmp_path, monkeypatch):
    module, store, job, root, _ = repair_fixture(tmp_path, monkeypatch)
    original = (root / 'lib/calculate.ts').read_text()
    class Agents:
        def generate(self, schema, *args, **kwargs):
            if schema.__name__ == 'AppRepairAnalysis':
                return {'diagnosis': 'wrong total', 'recommendation': 'repair helper', 'files': ['lib/calculate.ts']}
            return {'content': "import sqlite from 'sqlite'; export const version=sqlite;"}
    result = module.repair_job(job, Agents(), store)
    assert result['status'] == 'FAILED'
    assert 'unsupported dependencies' in result['events'][-1]['payload']['reason']
    assert (root / 'lib/calculate.ts').read_text() == original


def test_repair_target_is_complete_or_rejected_never_truncated(tmp_path):
    plan = calculator_plan()
    target = tmp_path / 'app/api/calculate/route.ts'
    target.parent.mkdir(parents=True)
    target.write_text('x' * 16000)
    with pytest.raises(ValueError, match='Complete repair target'):
        app_coding_context(calculator_spec(), plan, tmp_path, 'app/api/calculate/route.ts', required=True)
    with pytest.raises(ValueError, match='existing approved'):
        app_coding_context(calculator_spec(), plan, tmp_path, 'lib/unapproved.ts', required=True)


def test_import_preflight_does_not_treat_jsx_or_from_variable_as_dependencies(tmp_path):
    from forge.workspace import unsupported_imports,normalize_app_source
    source='''use client;
import {useState} from 'react';
export default function Page(){const [from,setFrom]=useState<'C'|'F'>('C');
return <><label htmlFor="from">From:</label><select id="from" value={from} onChange={e=>setFrom(e.target.value as 'C'|'F')}/></>;}'''
    assert unsupported_imports(tmp_path,'app/page.tsx',source)==[]
    assert normalize_app_source('app/page.tsx',source).startswith('"use client";')
    assert unsupported_imports(tmp_path,'app/page.tsx',"import{a}from'uuid'; export {x} from 'sqlite';")==['sqlite','uuid']
    assert unsupported_imports(tmp_path,'app/page.tsx',"import type {X} from 'extra'; import('axios'); require('sqlite3');")==['axios','extra','sqlite3']


def test_generation_resume_preserves_completed_work_and_requires_same_approval(tmp_path,monkeypatch):
    import forge.builders as module
    from forge.schemas import RequirementsDocument,ImplementationPlan
    from forge.workflow import review_fingerprint
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    requirements=RequirementsDocument.model_validate(calculator_spec()).model_dump()
    plan=ImplementationPlan.model_validate(calculator_plan()).model_dump()
    fingerprint=review_fingerprint(requirements,plan)
    store.event(job,'PLAN_REVIEW',{'requirements':requirements,'plan':plan})
    store.event(job,'APPROVED',{'fingerprint':fingerprint})
    root=tmp_path/'workspace'/job
    backend=root/'app/api/calculate/route.ts';backend.parent.mkdir(parents=True)
    backend.write_text('export const preserved=123;')
    (root/'package.json').write_text('{}')
    store.event(job,'BUILDING',{})
    store.event(job,'FAILED',{'reason':'frontend generation interrupted'})
    class Agents:
        def build_app_file(self,owner,file,plan,requirements,root):
            assert owner=='frontend' and file=='app/page.tsx'
            assert (root/'app/api/calculate/route.ts').read_text()=='export const preserved=123;'
            return {'content':'export default function Page(){return null;}'}
    result=module.build_job(job,Agents(),store,resume=True)
    assert result['status']=='GENERATED_UNVERIFIED'
    assert backend.read_text()=='export const preserved=123;'
    assert sum(e['status']=='GENERATION_RETRY' for e in result['events'])==1
    store.event(job,'FAILED',{})
    with pytest.raises(ValueError,match='cannot resume'):module.build_job(job,Agents(),store,resume=True)


def test_generation_resume_rejects_stale_approval_and_unapproved_run(tmp_path,monkeypatch):
    import forge.builders as module
    from forge.schemas import RequirementsDocument,ImplementationPlan
    monkeypatch.setattr(module,'PROJECT',tmp_path)
    store=JobStore(tmp_path/'jobs.db');job=store.create()
    with pytest.raises(ValueError,match='cannot resume'):module.build_job(job,None,store,resume=True)
    store.event(job,'PLAN_REVIEW',{'requirements':RequirementsDocument.model_validate(calculator_spec()).model_dump(),
                                 'plan':ImplementationPlan.model_validate(calculator_plan()).model_dump()})
    store.event(job,'APPROVED',{'fingerprint':'0'*64})
    store.event(job,'BUILDING',{});store.event(job,'FAILED',{})
    with pytest.raises(ValueError,match='Approved revision'):module.build_job(job,None,store,resume=True)
