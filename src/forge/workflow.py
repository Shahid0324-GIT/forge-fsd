import hashlib
import json
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from langsmith import tracing_context
from pydantic import Field, StrictBool

from forge.persistence import JobStore
from forge.handoffs import record_handoff
from forge.schemas import ApplicationRequest, Boundary, ImplementationPlan, RequirementsDocument, AppBrief,AppAcceptancePlan,validate_app_contract


class Approval(Boundary):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved: StrictBool
    actor: Literal['local_cli','local_dashboard'] = 'local_cli'


class Answers(Boundary):
    answers: list[str] = Field(min_length=1, max_length=3)


class State(TypedDict, total=False):
    job_id: str
    description: str
    requirements: dict
    plan: dict
    calls: int
    rounds: int
    clarifications: list[dict]
    fingerprint: str
    status: str


def review_fingerprint(requirements, plan):
    raw = json.dumps({"requirements": requirements, "plan": plan}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def build_graph(agents, store: JobStore, checkpointer=None):
    def request_context(state):
        return json.dumps({'request':state['description'],'human_clarifications':state['clarifications']}) if state.get('clarifications') else state['description']

    def budget(state):
        limit=5 if state.get('requirements',{}).get('spec_version')==2 else 4
        if state.get("calls", 0) >= limit:
            raise ValueError(f"Model-node budget exhausted (maximum {limit} including clarifications)")

    def requirements(state):
        budget(state)
        store.event(state["job_id"], "REQUIREMENTS", {"delegated_to": "requirements_agent"})
        context = request_context(state)
        record_handoff(store,state['job_id'],'coordinator','requirements_agent',
                       'Classify the request and prepare a business brief or focused response.',
                       {'original_request':context},agents=agents)
        proposal=agents.requirements(context)
        data=proposal.model_dump() if hasattr(proposal,'model_dump') else proposal
        if data.get('intent') in {'help','out_of_scope'}:
            store.event(state['job_id'],'REQUEST_ANSWERED',{'intent':data['intent'],'message':data['message']})
            return {'status':'REQUEST_ANSWERED','calls':state.get('calls',0)+1}
        if data.get('spec_version')==2:
            # Compatibility with injected fixtures supplying a complete v2 document.
            if 'scenarios' in data:
                RequirementsDocument.model_validate(data)
                data={key:value for key,value in data.items() if key in AppBrief.model_fields}
            result=AppBrief.model_validate(data)
        else:result=RequirementsDocument.model_validate(data)
        store.event(state["job_id"], "REQUIREMENTS_READY", result.model_dump())
        return {"requirements": result.model_dump(), "calls": state.get("calls", 0) + 1}

    def route(state):
        if state.get('status')=='REQUEST_ANSWERED':return END
        return "clarify" if state["requirements"]["open_questions"] else "architect"

    def clarify(state):
        if state.get("rounds", 0) >= 2:
            raise ValueError("Clarification round budget exhausted (maximum two)")
        store.event(state["job_id"], "AWAITING_CLARIFICATION", {"questions": state["requirements"]["open_questions"]})
        return {"status": "AWAITING_CLARIFICATION"}

    def answer_gate(state):
        questions = state["requirements"]["open_questions"]
        value = Answers.model_validate(interrupt({"kind": "clarification", "questions": questions}))
        pairs = [{"question": q, "answer": a} for q, a in zip(questions, value.answers, strict=True)]
        store.event(state["job_id"], "CLARIFICATION_ANSWERED", {"answers": pairs})
        return {"clarifications": state.get("clarifications", []) + pairs, "rounds": state.get("rounds", 0) + 1}

    def architect(state):
        budget(state)
        store.event(state["job_id"], "PLANNING", {"delegated_to": "architect_agent"})
        schema=AppBrief if state['requirements'].get('spec_version')==2 else RequirementsDocument
        document=schema.model_validate(state['requirements'])
        record_handoff(store,state['job_id'],'requirements_agent','architect_agent',
                       'Turn the saved requirements and human answers into an implementation plan.',
                       {'requirements':document.model_dump(),'original_request':request_context(state)},agents=agents)
        proposal=agents.plan(document,original_request=request_context(state)) if document.spec_version==2 else agents.plan(document)
        result = ImplementationPlan.model_validate(proposal)
        validate_app_contract(document,result)
        return {"plan": result.model_dump(), "calls": state.get("calls", 0) + 1}

    def acceptance(state):
        budget(state)
        store.event(state['job_id'],'TEST_PLANNING',{'delegated_to':'qa'})
        brief=AppBrief.model_validate(state['requirements'])
        plan=ImplementationPlan.model_validate(state['plan'])
        record_handoff(store,state['job_id'],'architect_agent','qa',
                       'Design acceptance checks against the same requirements, interfaces and original request.',
                       {'requirements':brief.model_dump(),'plan':plan.model_dump(),'original_request':request_context(state)},agents=agents)
        tests=AppAcceptancePlan.model_validate(agents.acceptance(brief,plan,request_context(state)))
        if tests.database!=brief.database:raise ValueError('QA database choice differs from requirements')
        document=RequirementsDocument.model_validate({**brief.model_dump(),'scenarios':[s.model_dump() for s in tests.scenarios]})
        validate_app_contract(document,plan)
        store.event(state['job_id'],'REQUIREMENTS_READY',document.model_dump())
        return {'requirements':document.model_dump(),'calls':state.get('calls',0)+1}

    def review(state):
        if state['plan'].get('design'):
            from forge.workspace import app_coding_context
            root=store.path.parent/'.context-preflight'/state['job_id']
            for task in state['plan']['tasks']:
                for file in task['files']:
                    app_coding_context(state['requirements'],state['plan'],root,file)
        fingerprint = review_fingerprint(state["requirements"], state["plan"])
        store.event(state["job_id"], "PLAN_REVIEW", {"requirements": state["requirements"], "plan": state["plan"], "fingerprint": fingerprint})
        return {"fingerprint": fingerprint, "status": "PLAN_REVIEW"}

    def approval_gate(state):
        decision = Approval.model_validate(interrupt({"kind": "plan_approval", "fingerprint": state["fingerprint"], "requirements": state["requirements"], "plan": state["plan"]}))
        if decision.fingerprint != state["fingerprint"]:
            raise ValueError("Approval does not match the reviewed revision")
        status = "APPROVED" if decision.approved else "CANCELLED"
        store.event(state["job_id"], status, decision.model_dump())
        return {"status": status}

    graph = StateGraph(State)
    for name, node in (("requirements", requirements), ("clarify", clarify),
                       ("answers", answer_gate), ("architect", architect),
                       ("acceptance",acceptance),("review", review), ("approval", approval_gate)):
        graph.add_node(name, node)
    graph.add_edge(START, "requirements")
    graph.add_conditional_edges("requirements", route)
    graph.add_edge("clarify", "answers")
    graph.add_edge("answers", "requirements")
    graph.add_conditional_edges('architect',lambda state:'acceptance' if state['requirements'].get('spec_version')==2 else 'review')
    graph.add_edge('acceptance','review')
    graph.add_edge("review", "approval")
    graph.add_edge("approval", END)
    return graph.compile(checkpointer=checkpointer)


def config(job_id):
    return {"configurable": {"thread_id": job_id}, "recursion_limit": 20}


def invoke_job(job_id, graph_input, agents, store):
    if agents is not None:agents.invocation_context={**getattr(agents,'invocation_context',{}),'job_id':job_id}
    try:
        with store.checkpoints() as saver, tracing_context(enabled=False):
            build_graph(agents, store, saver).invoke(graph_input, config(job_id)) # type: ignore
    except Exception as exc:
        store.event(job_id, "FAILED", {"error_type": type(exc).__name__, "reason": str(exc)[:2000]})
    return store.read(job_id)


def run_job(description, agents, store):
    request = ApplicationRequest(description=description,model=getattr(agents,'model_name','qwen2.5-coder:3b'))
    job_id = store.create(request.model_dump())
    return invoke_job(job_id, {"job_id": job_id, "description": request.description, "calls": 0, "rounds": 0}, agents, store)


def planning_retryable(record):
    return record['status']=='FAILED' and not any(e['status'] in {'APPROVED','PLAN_REVIEW'} for e in record['events'])


def revise_review(job_id,requirements,plan,reason,store):
    """Apply a disclosed reviewer correction; invalidate the old approval revision."""
    record=store.read(job_id)
    if record['status']!='PLAN_REVIEW':raise ValueError('Only an unapproved review can be revised')
    if not reason.strip() or len(reason)>1000:raise ValueError('A bounded revision reason is required')
    document=RequirementsDocument.model_validate(requirements)
    architecture=ImplementationPlan.model_validate(plan)
    validate_app_contract(document,architecture)
    fingerprint=review_fingerprint(document.model_dump(),architecture.model_dump())
    with store.checkpoints() as saver,tracing_context(enabled=False):
        graph=build_graph(None,store,saver)
        snapshot=graph.get_state(config(job_id))
        if snapshot.next!=('approval',):raise ValueError('Review has no pending approval checkpoint')
        previous=snapshot.values['fingerprint']
        graph.update_state(config(job_id),{'requirements':document.model_dump(),'plan':architecture.model_dump(),
                                          'fingerprint':fingerprint,'status':'PLAN_REVIEW'},as_node='review')
        graph.invoke(None,config(job_id))
    store.event(job_id,'PLAN_REVIEW',{'requirements':document.model_dump(),'plan':architecture.model_dump(),
                                    'fingerprint':fingerprint,'previous_fingerprint':previous,
                                    'revised_by':'developer_review','revision_reason':reason})
    return store.read(job_id)


def retry_planning(job_id,agents,store):
    record=store.read(job_id)
    if not planning_retryable(record):raise ValueError('Only failed pre-review planning can be retried')
    if sum(e['status']=='PLANNING_RETRY' for e in record['events'])>=2:
        raise ValueError('Planning retry limit exhausted; start a new request')
    with store.checkpoints() as saver,tracing_context(enabled=False):
        snapshot=build_graph(agents,store,saver).get_state(config(job_id))
    if not snapshot.next or not set(snapshot.next).issubset({'requirements','architect','acceptance'}):
        raise ValueError('No failed planning checkpoint is available; start a new request')
    store.event(job_id,'PLANNING_RETRY',{'nodes':list(snapshot.next)},update_status=False)
    return invoke_job(job_id,None,agents,store)


def resume_job(job_id, decision, agents, store):
    record = store.read(job_id)
    with store.checkpoints() as saver, tracing_context(enabled=False):
        graph = build_graph(agents, store, saver)
        snapshot = graph.get_state(config(job_id)) # type: ignore
    if not snapshot.next or not snapshot.values:
        raise ValueError("No resumable checkpoint for this job; older jobs must be replanned")
    if record["status"] == "PLAN_REVIEW":
        RequirementsDocument.model_validate(snapshot.values["requirements"])
        ImplementationPlan.model_validate(snapshot.values["plan"])
        parsed = Approval.model_validate(decision)
        if parsed.fingerprint != snapshot.values["fingerprint"]:
            raise ValueError("Stale approval: fingerprint does not match the current review")
    elif record["status"] == "AWAITING_CLARIFICATION":
        parsed = Answers.model_validate(decision)
        if len(parsed.answers) != len(snapshot.values["requirements"]["open_questions"]):
            raise ValueError("Provide exactly one answer per pending question")
        if any(not answer.strip() or len(answer) > 1000 for answer in parsed.answers):
            raise ValueError("Answers must be nonempty and at most 1000 characters")
    else:
        raise ValueError(f"Cannot resume a job in {record['status']}")
    return invoke_job(job_id, Command(resume=parsed.model_dump()), agents, store)
