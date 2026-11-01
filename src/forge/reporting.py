import json
from datetime import datetime,timezone
from uuid import uuid4

from pydantic import Field

from forge.builders import PROJECT
from forge.schemas import Boundary
from forge.security import security_gate
from forge.workspace import source_fingerprint
from forge.browser_testing import browser_gate


class ReadinessNotes(Boundary):
    local_setup: list[str] = Field(min_length=1,max_length=6)
    deployment_limitations: list[str] = Field(min_length=1,max_length=6)


def write_report(job_id,agents,store):
    record=store.read(job_id);root=PROJECT/'workspace'/job_id
    if not root.is_dir():raise ValueError('Report requires a generated source workspace')
    fingerprint=source_fingerprint(root)
    sections={}
    for key,status in [('functional','FUNCTIONALLY_VERIFIED'),('security','SECURITY_PASSED')]:
        payload=next((e['payload'] for e in reversed(record['events']) if e['status']==status and e['payload'].get('source_fingerprint')==fingerprint),None)
        sections[key]=json.loads(open(payload['report'],encoding='utf-8').read()) if payload else None
    functional=sections['functional'] or {}
    results=functional.get('checks',{}).get('results',[])
    required={'typecheck','production_build','acceptance','persistence_restart'}
    review=next((e['payload'] for e in reversed(record['events']) if e['status']=='PLAN_REVIEW'),{})
    specification=review.get('requirements',{})
    stateless=specification.get('spec_version')==2 and specification.get('database')=='none'
    if stateless:required.remove('persistence_restart')
    if specification.get('spec_version')==2 and specification.get('database')=='sqlite':required.add('database_integrity')
    functionally_passed=(functional.get('source_fingerprint')==fingerprint and functional.get('source_unchanged') is True
        and functional.get('execution',{}).get('exit_code')==0
        and functional.get('checks',{}).get('passed') is True
        and required.issubset({r['name'] for r in results})
        and all(r.get('exit_code')==0 and not r.get('stopped') for r in results))
    current=bool(functionally_passed and sections['security'] and security_gate(sections['security']['checks'],sections['security']['source_unchanged']))
    automated=next((e['payload'] for e in reversed(record['events']) if e['status'] in {'AUTOMATED_BROWSER_PASSED','AUTOMATED_BROWSER_FAILED'} and e['payload'].get('source_fingerprint')==fingerprint),None)
    automated_report=json.loads(open(automated['report'],encoding='utf-8').read()) if automated else None
    current=current and browser_gate(record,fingerprint)
    browser=next((e['payload'] for e in reversed(record['events']) if e['status']=='BROWSER_QA_PASSED' and e['payload'].get('source_fingerprint')==fingerprint),None)
    adjustments=[e['payload'] for e in record['events'] if e['status']=='SOURCE_ADJUSTED']
    store.event(job_id,'READINESS',{'delegated_to':'readiness_agent'},update_status=False)
    notes=ReadinessNotes.model_validate(agents.generate(ReadinessNotes,
        'You are the Deployment-Readiness Agent, preparing documentation only. '
        'Do not deploy, request credentials or claim production readiness. '
        'Explain Node 24/npm setup, SQLite filesystem persistence, and that '
        'Vercel persistent CRUD needs the not-yet-implemented remote database adapter. '
        'Document no authentication and the limited scope of supplied manual and automated '
        'browser checks. Do not infer general browser coverage. Disclose developer/controller corrections. Use facts supplied, not invented checks.',
        {'stack':'Next.js App Router, TypeScript'+(' (stateless)' if stateless else ', local SQLite via node:sqlite'),
         'environment':{} if stateless else {'SQLITE_PATH':'./data/app.sqlite3'},
         'local_commands':['npm ci --ignore-scripts','npm run build','npm start'],
         'actual_checks_passed':current,'manual_browser_checks':browser,
         'automated_browser_checks':None if automated_report is None else {
             'profile':automated_report.get('profile'),'passed':automated_report.get('passed'),
             'results':[{'name':r['name'],'passed':r['passed']} for r in automated_report.get('browser',{}).get('results',[])],
             'limitations':automated_report.get('browser',{}).get('limitations',[])},
         'source_adjustments':adjustments,'cloud_deployed':False}))
    preview=next((e['payload'] for e in reversed(record['events']) if e['status']=='PREVIEW_RUNNING'),None)
    report={'job_id':job_id,'timestamp':datetime.now(timezone.utc).isoformat(),'source_fingerprint':fingerprint,
            'assessment':'LOCALLY_VERIFIED_WITH_LIMITATIONS' if current else 'UNVERIFIED',
            'cloud_deployed':False,'source_directory':str(root),'evidence':sections,
            'preview':preview if record['status']=='PREVIEW_RUNNING' else None,
            'environment':{} if stateless else {'SQLITE_PATH':{'default':'./data/app.sqlite3','secret':False}},
            'agent_notes':notes.model_dump(),
            'manual_browser_checks':browser,'source_adjustments':adjustments,
            'automated_browser_checks':automated_report,
            'known_limitations':['Browser interaction coverage for generated applications remains incomplete.',
                'Prompt evaluation uses five fixed attacks and a control; inspect per-case model and policy outcomes.',
                'Static scanning uses four custom rules, not a complete security assessment.',
                'Selected manual browser/API cases passed; automated cross-domain browser coverage is incomplete.' if browser else 'Browser UI validation has not yet been checked against API constraints.',
                'Preview data is disposable and expires with its container.',
                'Remote PostgreSQL is unimplemented. App CI/CD preparation, publishing and deployment are separate reviewed actions; this readiness report does not attest cloud deployment.']}
    directory=PROJECT/'artifacts/reports'/job_id;directory.mkdir(parents=True,exist_ok=True)
    path=directory/(uuid4().hex+'.json');path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    store.event(job_id,'REPORT_CREATED',{'report':str(path),'source_fingerprint':fingerprint,'assessment':report['assessment']},update_status=False)
    return store.read(job_id)
