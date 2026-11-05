"""Internal engineering review before the operator is asked to approve business scope."""
import hashlib
import json
from pathlib import Path
from enum import Enum
from typing import Annotated,Literal,Union

from pydantic import Field,create_model

from forge.handoffs import record_handoff
from forge.runtime_reference import runtime_references
from forge.tasks import CheckEvidence,Envelope,Observation,Task,TaskBlockedError,TaskConflict
from forge import documentation


class DesignIssue(Envelope):
    field: Literal['design','files','interfaces','test_strategy','acceptance_criteria','assumptions']
    evidence: str = Field(min_length=1,max_length=700,description='Exact quote from this proposal field; use [] for an absent interface list.')
    basis_reference: str = Field(min_length=1,max_length=300,
        description='Select a supplied basis_sources reference establishing the expected requirement/runtime constraint, or a conflicting proposal statement. Do not invent a requirement or copy/paraphrase a quotation.')
    problem: str = Field(min_length=1,max_length=600)
    correction: str = Field(min_length=1,max_length=900,description='A technical decision the planner/builders must make, never a request for the user to supply implementation details.')


class ImplementationReview(Envelope):
    assessed_files: list[str] = Field(max_length=20)
    issues: list[DesignIssue] = Field(max_length=3)


INSTRUCTION='''Review a DESIGN, before source implementation. The agents own all
technical decisions; the user supplies business behavior and constraints.
1. Read the original request and the entire current proposal. Check whether each
concern is ALREADY addressed before calling it missing. A planned validation flow
is not broken merely because its source code does not exist yet. Read test steps
in order; do not report an assertion missing when that assertion is present.
2. Block only an omitted explicit requirement, an actual internal contradiction,
an incompatible runtime choice, or an undefined shared boundary needed by builders.
Unspecified error placement, styling, additional security and platform support are
builder decisions or optional suggestions, never new business requirements.
3. For a technical doubt, consult supplied official documentation or request
lookup_documentation BEFORE asserting the API/storage/framework cannot work.
Installed-version capabilities outrank general documentation. Reading docs does
not make a new requirement mandatory. Withdraw concerns the sources do not support.
4. Return assessed_files covering every declared file exactly once and at most
three blocking issues. issues=[] is correct when no concrete contradiction remains.
Quote the actual proposal field and select a relevant basis_sources reference.
An internal contradiction needs TWO DIFFERENT conflicting statements; a statement
cannot contradict itself. Explain the conflict, not a hypothetical broken app.
5. Corrections belong to the planner/builders. Never request human code, API paths,
types or folders, or claim compilation, execution or approval.'''


def _strings(value):
    if isinstance(value,str):yield value
    elif isinstance(value,list):
        for item in value:yield from _strings(item)
    elif isinstance(value,dict):
        for item in value.values():yield from _strings(item)


def basis_sources(context,proposal):
    def leaves(value,path):
        if isinstance(value,str) and value:yield path,value
        elif isinstance(value,dict):
            for key,item in value.items():yield from leaves(item,path+'/'+key)
        elif isinstance(value,list):
            for index,item in enumerate(value):yield from leaves(item,path+'/'+str(index))
    request={key:context.get(key,[]) for key in ('original_request','human_clarifications','human_review_feedback')}
    runtime={key:context[key] for key in ('runtime_capabilities','runtime_references','verification_capabilities')}
    documents={str(index):{str(source_index):{'excerpt':source['excerpt']}
        for source_index,source in enumerate(result.get('sources',[])) if source.get('status')=='ok'}
        for index,result in enumerate(context.get('documentation_evidence',[]))}
    return dict([*leaves(request,'request'),*leaves(runtime,'runtime'),*leaves(proposal,'proposal'),
        *leaves(documents,'documentation')])


def _validate(decision,proposal,context=None):
    paths=[file['path'] for file in proposal['files']]
    if len(decision.assessed_files)!=len(paths) or set(decision.assessed_files)!=set(paths):
        raise ValueError('Implementation review must assess every declared file exactly once')
    for issue in decision.issues:
        value=proposal[issue.field]
        texts=[json.dumps(value,ensure_ascii=False),*_strings(value)]
        if not issue.evidence.strip() or not any(issue.evidence in text for text in texts):
            raise ValueError('Implementation findings must quote their actual proposal field: '+issue.field)
        if context is not None:
            sources=basis_sources(context,proposal)
            if issue.basis_reference not in sources:
                raise ValueError('Implementation issue basis must reference a supplied request/runtime/proposal fact')
            if issue.basis_reference.startswith('proposal/') and sources[issue.basis_reference]==issue.evidence:
                raise ValueError('An internal contradiction needs a different conflicting proposal quote')


def review_schema(proposal,sources=None):
    # Encode empty-field references in the decoding schema. Small models should
    # not have to invent a quotation for an absent interface/assumption list.
    variants=[]
    references=Enum('ReviewBasis',{f'fact_{index}':reference for index,reference in enumerate(sources or {})},type=str) if sources else str
    for field in DesignIssue.model_fields['field'].annotation.__args__:
        fields={'field':(Literal[field],...),'basis_reference':(references,...)}
        if proposal[field]==[]:fields['evidence']=(Literal['[]'],...)
        variants.append(create_model('ReviewIssue_'+field,__base__=DesignIssue,**fields))
    issue=Annotated[Union[tuple(variants)],Field(discriminator='field')]
    return create_model('ImplementationReview',__base__=ImplementationReview,
        assessed_files=(list[Literal[tuple(file['path'] for file in proposal['files'])]],
            Field(min_length=len(proposal['files']),max_length=len(proposal['files']))),
        issues=(list[issue],Field(max_length=3)))


def review_design(ledger,state,agents,draft,data):
    ledger.assert_active(state)
    proposal=draft.model_dump();digest=hashlib.sha256(draft.model_dump_json().encode()).hexdigest()
    context={key:data.get(key,[] if key!='original_request' else '')
        for key in ('original_request','human_clarifications','human_review_feedback')}
    context.update(proposal=proposal,runtime_capabilities=data['runtime_capabilities'],
        runtime_references=runtime_references(draft.database),verification_capabilities=data['verification_capabilities'])
    sources=basis_sources(context,proposal)
    context['basis_sources']=sources
    if len(json.dumps(context,separators=(',',':')))>28000:
        raise ValueError('Implementation review packet exceeds its capacity; consolidate the agent-authored design/contracts without dropping requirements')
    child=ledger.reserve_action(ledger.start(ledger.create(Task(parent_id=state.task.id,owner='implementation_reviewer',
        goal='Resolve technical design and interface defects internally before scope approval.',
        inputs={'parent_revision':state.revision,'proposal_sha256':digest},required_checks=['implementation_review']))),'implementation_reviewer')
    schema=review_schema(proposal,sources)
    previous=getattr(agents,'invocation_context',{});activity=getattr(agents,'activity',None)
    try:
        request=dict(context);decision=None;protocol_errors=0;researched=False
        research_available=documentation.enabled(agents)
        def consult(decision):
            nonlocal context,sources,schema,researched
            query=' '.join(issue.problem+' '+issue.evidence for issue in decision.issues)[:300]
            reference=documentation.lookup_for_agent(agents,{'tool':'lookup_documentation','query':query})
            context={**context,'documentation_evidence':[reference]}
            sources=basis_sources(context,proposal);context['basis_sources']=sources
            schema=review_schema(proposal,sources);researched=True
        for attempt in range(3 if research_available else 2):
            ledger.assert_active(state);ledger.assert_active(child)
            record_handoff(ledger.store,ledger.job_id,'planner','implementation_reviewer',
                'Review implementation decisions internally; the user is not an API/type/folder designer.',request,
                agents=agents,task_id=child.task.id,parent_task_id=state.task.id,task_state=child)
            agents.activity=lambda status,payload:ledger.store.event(ledger.job_id,status,payload,update_status=False)
            try:
                # Normalize enum references back to the durable plain-string protocol.
                parsed=schema.model_validate(agents.generate(schema,INSTRUCTION,request,coding=True))
                decision=ImplementationReview.model_validate(parsed.model_dump(mode='json'))
                _validate(decision,proposal,context)
                if decision.issues and research_available and not researched:
                    consult(decision)
                    request={**context,'previous_decision':decision.model_dump(),
                        'research_instruction':'Reassess your findings against the actual proposal, original scope and retrieved documentation. Withdraw unsupported concerns and do not invent security, placement or platform requirements. Return the complete final review; [] is valid.'}
                    continue
                break
            except (TaskConflict,TaskBlockedError):raise
            except ValueError as exc:
                if protocol_errors:raise TaskBlockedError('Implementation reviewer returned invalid protocol twice; the user is not responsible for correcting the design. '+str(exc)) from exc
                protocol_errors+=1
                if decision and decision.issues and research_available and not researched:consult(decision)
                request={**context,'previous_decision':decision.model_dump() if decision else None,
                    'review_validation_error':str(exc),'correction_instruction':'Correct your own review references and assess every declared file. Do not rewrite the design or ask the user technical questions.'}
        else:raise TaskBlockedError('Internal review recovery budget exhausted before a validated final decision; no user technical decision requested.')
        ledger.assert_active(state)
        directory=ledger.store.path.parent/'implementation-reviews'/ledger.job_id;directory.mkdir(parents=True,exist_ok=True)
        path=directory/(child.task.id+'.json')
        packet={'version':1,'task_id':child.task.id,'parent_task_id':state.task.id,'parent_revision':state.revision,
            'proposal_sha256':digest,'decision':decision.model_dump(),
            'basis_evidence':{issue.basis_reference:sources[issue.basis_reference] for issue in decision.issues},
            'documentation_evidence':context.get('documentation_evidence',[]),
            'scope':'Internal technical critique only; compilation and application behavior have not executed.'}
        path.write_text(json.dumps(packet,indent=2),encoding='utf-8');fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
        ledger.observe(child,Observation(revision=child.revision,fingerprint=fingerprint,checks=[CheckEvidence(
            check='implementation_review',exit_code=0,fingerprint=fingerprint,report=str(path.resolve()),
            summary='Technical critique validated; findings belong to the planner, not the user.')]))
        ledger.store.event(ledger.job_id,'IMPLEMENTATION_REVIEWED',{'task_id':state.task.id,'review_task_id':child.task.id,
            'issues':[issue.model_dump() for issue in decision.issues],'report':str(path.resolve()),
            'summary':'Internal implementation findings sent back to the planner.' if decision.issues else 'No unresolved internal engineering findings; execution remains unverified.'},update_status=False)
        return {'report':str(path.resolve()),'decision':decision.model_dump(),'proposal_sha256':digest}
    except Exception:
        current=ledger.read(child.task.id)
        if current.status=='running':ledger.pause(current,'Internal implementation review requires recovery; no user technical decision requested.',action_finished=True)
        raise
    finally:agents.invocation_context=previous;agents.activity=activity


def prior_review(ledger,state,draft):
    digest=hashlib.sha256(draft.model_dump_json().encode()).hexdigest()
    for event in reversed(ledger.store.read(ledger.job_id)['events']):
        if event['status']!='IMPLEMENTATION_REVIEWED' or event['payload'].get('task_id')!=state.task.id:continue
        path=Path(event['payload']['report']).resolve()
        if not path.is_relative_to((ledger.store.path.parent/'implementation-reviews'/ledger.job_id).resolve()):continue
        try:
            child=ledger.read(event['payload']['review_task_id'])
            if child.status!='completed' or child.task.parent_id!=state.task.id:continue
            if not path.is_file() or path.stat().st_size>40000:continue
            fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
            if not any(check.check=='implementation_review' and check.exit_code==0 and check.fingerprint==fingerprint
                for observation in child.observations for check in observation.checks):continue
            packet=json.loads(path.read_text(encoding='utf-8'))
            if packet['parent_revision']==state.revision and packet['proposal_sha256']==digest:
                decision=ImplementationReview.model_validate(packet['decision']);_validate(decision,draft.model_dump())
                return {**decision.model_dump(),'basis_evidence':packet.get('basis_evidence',{}),
                    'documentation_evidence':packet.get('documentation_evidence',[]),'report':str(path),
                    'scope':'Evidence for this proposal/revision only; model critique is not proof of implementation correctness.'}
        except (OSError,ValueError,KeyError):continue
    return None
