from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from forge.schemas import ImplementationPlan, RequirementsDocument, validate_app_contract
from forge.workflow import review_fingerprint
from forge.handoffs import record_handoff
from forge.workspace import OWNERS, FileOperation, safe_path, seed_workspace, source_fingerprint, write_owned, plan_owners,normalize_app_source,ordered_owner_files,app_coding_context


PROJECT = Path(__file__).resolve().parents[2]


class BuildState(TypedDict):
    job_id: str
    requirements: dict
    plan: dict
    root: str
    resume: bool


def builder_subgraph(agents, store):
    def generate(owner):
        def node(state):
            root = Path(state["root"])
            plan=ImplementationPlan.model_validate(state['plan'])
            owners=plan_owners(plan)
            ordered=ordered_owner_files(plan,owner) if plan.spec_version==2 else sorted(owners[owner])
            for relative in ordered:
                target=safe_path(root, relative)
                if state.get('resume') and target.is_file():continue
                baseline = target.read_text(encoding="utf-8") if target.exists() else ''
                store.event(state["job_id"], "BUILDING", {"delegated_to": f"{owner}_builder", "file": relative})
                if plan.spec_version==2:
                    context=app_coding_context(state['requirements'],plan.model_dump(),root,relative)
                    record_handoff(store,state['job_id'],'implementation_coordinator',f'{owner}_builder',
                                   f'Implement {relative} using the approved contract and available work from preceding builders.',context)
                    result=FileOperation.model_validate(agents.build_app_file(owner,relative,plan.model_dump(),state['requirements'],root))
                else:result = FileOperation.model_validate(agents.build_file(owner, relative, baseline, state["requirements"]))
                if plan.spec_version==2:
                    normalized=normalize_app_source(relative,result.content)
                    if normalized!=result.content:
                        store.event(state['job_id'],'SOURCE_ADJUSTED',{'file':relative,'rule':'platform-source-normalization','actor':'framework_controller'},update_status=False)
                        result=FileOperation(content=normalized)
                write_owned(root, owner, relative, result.content,owners)
            return {}
        return node

    graph = StateGraph(BuildState)
    graph.add_node("backend_builder", generate("backend"))
    graph.add_node("frontend_builder", generate("frontend"))
    graph.add_edge(START, "backend_builder")
    graph.add_edge("backend_builder", "frontend_builder")
    graph.add_edge("frontend_builder", END)
    return graph.compile()


def build_retryable(record):
    return (record['status']=='FAILED' and any(e['status']=='APPROVED' for e in record['events'])
            and any(e['status']=='BUILDING' for e in record['events'])
            and not any(e['status']=='GENERATED_UNVERIFIED' for e in record['events'])
            and sum(e['status']=='GENERATION_RETRY' for e in record['events'])<1
            and next((e['payload']['plan'].get('spec_version') for e in reversed(record['events']) if e['status']=='PLAN_REVIEW'),None)==2)


def build_job(job_id, agents, store, *, resume=False):
    record = store.read(job_id)
    if resume and not build_retryable(record):raise ValueError('Generation cannot resume: no eligible interrupted approved build or retry limit exhausted')
    if not resume and record["status"] != "APPROVED":
        raise ValueError("Build requires an explicitly approved plan")
    review = next(e["payload"] for e in reversed(record["events"]) if e["status"] == "PLAN_REVIEW")
    approval = next(e['payload'] for e in reversed(record['events']) if e['status']=='APPROVED')
    requirements = RequirementsDocument.model_validate(review["requirements"])
    plan = ImplementationPlan.model_validate(review["plan"])
    if review_fingerprint(review['requirements'],review['plan']) != approval["fingerprint"]:
        raise ValueError("Approved revision does not match build inputs")
    validate_app_contract(requirements,plan)
    for owner, files in (OWNERS.items() if plan.spec_version==1 else []):
        planned = {file for task in plan.tasks if task.owner == owner for file in task.files}
        if planned != files:
            raise ValueError("Approved manifest must match the supported task template")
    root = PROJECT / "workspace" / job_id
    try:
        if resume:
            # A retry preserves partial source; every resulting file still needs verification.
            safe_path(root,'package.json')
            if not root.is_dir():raise ValueError('Partial generation workspace is missing')
            store.event(job_id,'GENERATION_RETRY',{'source_fingerprint':source_fingerprint(root),'strategy':'generate_missing_files','maximum':1},update_status=False)
        else:seed_workspace(PROJECT / "templates" / "task-app", root,generic=plan.spec_version==2)
        store.event(job_id, "BUILDING", {"workspace": str(root), "approval": approval["fingerprint"]})
        # A parent graph delegates to the compiled implementation subgraph.
        parent = StateGraph(BuildState)
        parent.add_node("implementation_coordinator", builder_subgraph(agents, store))
        parent.add_edge(START, "implementation_coordinator")
        parent.add_edge("implementation_coordinator", END)
        with tracing_context(enabled=False):
            parent.compile().invoke({"job_id": job_id, "root": str(root), "requirements": requirements.model_dump(), "plan": plan.model_dump(),'resume':resume}, {"recursion_limit": 10})
        store.event(job_id, "GENERATED_UNVERIFIED", {"workspace": str(root), "source_fingerprint": source_fingerprint(root)})
    except Exception as exc:
        store.event(job_id, "FAILED", {"error_type": type(exc).__name__, "reason": str(exc)[:2000], "workspace": str(root)})
    return store.read(job_id)
