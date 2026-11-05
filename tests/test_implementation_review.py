from forge.autonomous_planning import AppDraft,plan_app,continue_draft
from forge.persistence import JobStore
from forge.tasks import TaskBlockedError,TaskLedger
from test_autonomous_planning import Agent,draft
import pytest


def reference(data,path):
    return next(key for key,value in data['basis_sources'].items() if value==path)


def test_technical_findings_are_repaired_by_planner_without_human_code_guidance(tmp_path):
    bad=draft();bad.assumptions=['The browser can directly open a SQLite file']
    class Reviewing(Agent):
        def generate(self,schema,instruction,data,**kwargs):
            if schema is AppDraft and data.get('implementation_findings'):
                self.proposal=draft()
                assert data['implementation_findings']['issues'][0]['field']=='assumptions'
                assert data.get('human_clarifications',[])==[]
                assert data['original_request']=='Build a small interactive page.'
            if schema.__name__=='ImplementationReview' and data['proposal']['assumptions']:
                self.calls.append((schema,data))
                return schema.model_validate({'assessed_files':['app/page.tsx'],'issues':[{
                    'field':'assumptions','evidence':bad.assumptions[0],
                    'basis_reference':reference(data,'runtime/runtime_capabilities/storage'),
                    'problem':'Browser filesystem access is not available in this runtime.',
                    'correction':'Choose a supported runtime boundary internally.'}]})
            return super().generate(schema,instruction,data,**kwargs)
    agent=Reviewing(bad);store=JobStore(tmp_path/'jobs.sqlite3')
    result=plan_app('Build a small interactive page.',agent,store)
    assert result['status']=='AUTONOMOUS_DRAFT_READY'
    assert len([data for schema,data in agent.calls if schema is AppDraft])==2
    assert not any(event['status']=='AUTONOMOUS_INPUT_NEEDED' for event in result['events'])
    planner=next(task for task in TaskLedger(store,result['job_id']).list() if task.task.owner=='planner')
    assert planner.observations[0].checks[-1].exit_code==1
    assert 'filesystem' in planner.observations[0].checks[-1].summary


def test_review_corrects_its_own_ungrounded_evidence_without_rewriting_planner(tmp_path):
    class Reviewing(Agent):
        def generate(self,schema,instruction,data,**kwargs):
            if schema.__name__=='ImplementationReview' and not data.get('review_validation_error'):
                self.calls.append((schema,data))
                return schema.model_validate({'assessed_files':['app/page.tsx'],'issues':[{
                    'field':'design','evidence':'Invented quote','problem':'Unsupported claim',
                    'basis_reference':reference(data,'request/original_request'),
                    'correction':'Choose an internal correction'}]})
            return super().generate(schema,instruction,data,**kwargs)
    agent=Reviewing(draft());result=plan_app('Build a small interactive page.',agent,JobStore(tmp_path/'jobs.sqlite3'))
    assert result['status']=='AUTONOMOUS_DRAFT_READY'
    assert len([data for schema,data in agent.calls if schema is AppDraft])==1
    reviews=[data for schema,data in agent.calls if schema.__name__=='ImplementationReview']
    assert len(reviews)==2 and 'quote' in reviews[-1]['review_validation_error']


def test_service_pause_preserves_candidate_and_retries_only_internal_review(tmp_path):
    class Unavailable(Agent):
        unavailable=True
        def generate(self,schema,instruction,data,**kwargs):
            if schema.__name__=='ImplementationReview' and self.unavailable:
                raise TaskBlockedError('Local model unavailable')
            return super().generate(schema,instruction,data,**kwargs)
    agent=Unavailable(draft());store=JobStore(tmp_path/'jobs.sqlite3')
    result=plan_app('Build a small interactive page.',agent,store)
    assert result['status']=='AUTONOMOUS_PAUSED'
    ledger=TaskLedger(store,result['job_id']);planner=next(task for task in ledger.list() if task.task.owner=='planner')
    assert not planner.observations
    ledger.resume(planner,additional_actions=1);agent.unavailable=False
    result=continue_draft(ledger,planner.task.id,agent)
    assert result['status']=='AUTONOMOUS_DRAFT_READY'
    assert len([data for schema,data in agent.calls if schema is AppDraft])==1


def test_repeated_invalid_review_stops_without_technical_question_or_plan_approval(tmp_path):
    class InvalidReview(Agent):
        def generate(self,schema,instruction,data,**kwargs):
            if schema.__name__=='ImplementationReview':
                self.calls.append((schema,data))
                return schema.model_validate({'assessed_files':['app/page.tsx'],'issues':[{
                    'field':'design','evidence':'An invented quotation','problem':'Ungrounded',
                    'basis_reference':reference(data,'request/original_request'),
                    'correction':'Decide internally'}]})
            return super().generate(schema,instruction,data,**kwargs)
    agent=InvalidReview(draft());store=JobStore(tmp_path/'jobs.sqlite3')
    result=plan_app('Build a small interactive page.',agent,store)
    assert result['status']=='AUTONOMOUS_PAUSED'
    assert len([data for schema,data in agent.calls if schema.__name__=='ImplementationReview'])==2
    assert not any(event['status'] in {'AUTONOMOUS_INPUT_NEEDED','AUTONOMOUS_DRAFT_READY'} for event in result['events'])


def test_absent_field_evidence_is_encoded_in_decoding_schema():
    from forge.implementation_review import review_schema
    schema=review_schema(draft().model_dump())
    issue={'field':'interfaces','evidence':'none','basis_reference':'request/original_request',
        'problem':'Missing boundary','correction':'Agree internally'}
    with pytest.raises(ValueError):schema.model_validate({'assessed_files':['app/page.tsx'],'issues':[issue]})
    value=schema.model_validate({'assessed_files':['app/page.tsx'],'issues':[{**issue,'evidence':'[]'}]})
    assert value.issues[0].evidence=='[]'


def test_invented_requirement_cannot_be_a_review_basis():
    from forge.implementation_review import ImplementationReview,_validate
    proposal=draft().model_dump()
    issue={'field':'design','evidence':proposal['design'],'basis_reference':'request/invented_mobile_requirement',
        'problem':'Unsupported demand','correction':'Add mobile support'}
    decision=ImplementationReview.model_validate({'assessed_files':['app/page.tsx'],'issues':[issue]})
    context={'original_request':'Build a page','runtime_capabilities':{},'runtime_references':{},'verification_capabilities':{}}
    with pytest.raises(ValueError,match='basis must reference'):_validate(decision,proposal,context)


def test_basis_references_are_schema_constrained_and_resolve_actual_supplied_facts():
    from forge.implementation_review import review_schema,basis_sources
    context={'original_request':'Save after reloading','runtime_capabilities':{'storage':'Server SQLite'},
        'runtime_references':{},'verification_capabilities':{}}
    sources=basis_sources(context,draft().model_dump())
    assert sources['request/original_request']=='Save after reloading'
    schema=review_schema(draft().model_dump(),sources)
    issue={'field':'design','evidence':'A quote','basis_reference':'request/made_up',
        'problem':'Claim','correction':'Change'}
    with pytest.raises(ValueError):schema.model_validate({'assessed_files':['app/page.tsx'],'issues':[issue]})


def test_technical_critique_is_rechecked_against_documentation_before_blocking(tmp_path):
    from test_documentation import page
    class Researching(Agent):
        documentation_enabled=True
        documentation_fetcher=staticmethod(page)
        def generate(self,schema,instruction,data,**kwargs):
            if schema.__name__=='ImplementationReview':
                self.calls.append((schema,data))
                if data.get('documentation_evidence'):
                    assert data['documentation_evidence'][0]['status']=='ok'
                    assert any(value.startswith('documentation/') for value in data['basis_sources'].values())
                    return schema.model_validate({'assessed_files':['app/page.tsx'],'issues':[]})
                return schema.model_validate({'assessed_files':['app/page.tsx'],'issues':[{
                    'field':'design','evidence':data['proposal']['design'],
                    'basis_reference':reference(data,'runtime/runtime_capabilities/storage'),
                    'problem':'Browser localStorage cannot persist after reloading.',
                    'correction':'Choose a supported storage mechanism.'}]})
            return super().generate(schema,instruction,data,**kwargs)
    value=draft();value.design='Browser localStorage will retain notes after reloading.'
    agent=Researching(value);store=JobStore(tmp_path/'jobs.sqlite3')
    result=plan_app('Build notes that remain after reloading.',agent,store)
    assert result['status']=='AUTONOMOUS_DRAFT_READY'
    assert len([data for schema,data in agent.calls if schema is AppDraft])==1
    assert len([data for schema,data in agent.calls if schema.__name__=='ImplementationReview'])==2
    assert any(event['status']=='DOCUMENTATION_LOOKUP_COMPLETED' for event in result['events'])
    from forge.implementation_review import prior_review
    ledger=TaskLedger(store,result['job_id']);planner=next(task for task in ledger.list() if task.task.owner=='planner')
    feedback=prior_review(ledger,planner,value)
    assert feedback['documentation_evidence'][0]['status']=='ok'


def test_unavailable_documentation_cannot_be_cited_as_a_technology_fact():
    from forge.implementation_review import basis_sources
    context={'original_request':'Build a page','runtime_capabilities':{},'runtime_references':{},'verification_capabilities':{},
        'documentation_evidence':[{'status':'unavailable','sources':[{'status':'unavailable','error':'Timeout'}]}]}
    assert not any(key.startswith('documentation/') for key in basis_sources(context,draft().model_dump()))


def test_compact_review_ids_preserve_facts_and_resolve_to_canonical_evidence():
    import json
    from forge.implementation_review import basis_sources,reference_ids,review_schema,resolved_review,_validate
    context={'original_request':'Retain notes after reloading','runtime_capabilities':{'storage':'Browser localStorage is supported.'},
        'runtime_references':{},'verification_capabilities':{}}
    proposal=draft().model_dump();sources=basis_sources(context,proposal);identifiers=reference_ids(sources)
    assert set(identifiers.values())==set(sources)
    key=next(key for key,path in identifiers.items() if path=='request/original_request')
    schema=review_schema(proposal,identifiers)
    wire=schema.model_validate({'assessed_files':['app/page.tsx'],'issues':[{'field':'design',
        'evidence':proposal['design'],'basis_reference':key,'problem':'Reload lifetime is unspecified.',
        'correction':'Define the requested reload behavior.'}]})
    decision=resolved_review(wire,identifiers)
    assert decision.issues[0].basis_reference=='request/original_request'
    _validate(decision,proposal,context)
    compact=schema.model_json_schema()
    assert compact['$defs']['ReviewBasis']['enum']==list(identifiers)
    assert len(json.dumps(compact))<len(json.dumps(review_schema(proposal,sources).model_json_schema()))
    with pytest.raises(ValueError,match='outside this evidence'):resolved_review(wire,{})
