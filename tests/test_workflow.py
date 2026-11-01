import pytest
from pydantic import ValidationError

from forge.persistence import JobStore
from forge.schemas import ImplementationPlan
from forge.workflow import run_job


def requirements(questions=None):
    return {"title": "Tasks", "entity": "task", "fields": ["title", "description", "status"],
            "operations": ["create", "read", "update", "delete"],
            "acceptance_criteria": ["Create task", "Read task", "Update task", "Delete task"],
            "assumptions": ["SQLite persists on local filesystem"], "open_questions": questions or []}


def plan():
    return {"framework": "nextjs-app-router", "database": "sqlite",
            "routes": ["GET /api/tasks", "POST /api/tasks", "GET /api/tasks/{id}", "PATCH /api/tasks/{id}", "DELETE /api/tasks/{id}"],
            "tasks": [{"owner": "frontend", "objective": "Build UI", "files": ["app/page.tsx"]},
                      {"owner": "backend", "objective": "Build API", "files": ["app/api/tasks/route.ts"]}],
            "verification": ["Build", "CRUD acceptance", "Invalid input"]}


class FakeAgents:
    def __init__(self, questions=None, invalid=False, broken_plan=False):
        self.questions, self.invalid, self.broken_plan = questions, invalid, broken_plan
        self.calls = []

    def requirements(self, description):
        self.calls.append("requirements")
        result = requirements(self.questions)
        if self.invalid:
            result["operations"] = ["read"]
        return result

    def plan(self, document):
        self.calls.append("architect")
        result = plan()
        if self.broken_plan:
            result["routes"] = ["POST /wrong"] * 5
        return result


def test_delegation_persists_plan_and_stops_for_review(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    agents = FakeAgents()
    result = run_job("Build a task management application", agents, store)
    assert result["status"] == "PLAN_REVIEW"
    assert agents.calls == ["requirements", "architect"]
    assert [e["status"] for e in result["events"]] == ["RECEIVED", "REQUIREMENTS", "REQUIREMENTS_READY", "PLANNING", "AGENT_HANDOFF", "PLAN_REVIEW"]
    handoff=next(e['payload'] for e in result['events'] if e['status']=='AGENT_HANDOFF')
    assert (handoff['sender'],handoff['recipient'])==('requirements_agent','architect_agent')
    assert JobStore(store.path).read(result["job_id"]) == result


def test_material_questions_prevent_planner_call(tmp_path):
    agents = FakeAgents(questions=["Can we limit this request to task CRUD?"])
    result = run_job("Build a task app with advanced collaboration", agents, JobStore(tmp_path / "jobs.db"))
    assert result["status"] == "AWAITING_CLARIFICATION"
    assert agents.calls == ["requirements"]


@pytest.mark.parametrize("invalid,broken_plan", [(True, False), (False, True)])
def test_bad_model_output_fails_with_inspectable_evidence(tmp_path, invalid, broken_plan):
    agents = FakeAgents(invalid=invalid, broken_plan=broken_plan)
    result = run_job("Build a task management application", agents, JobStore(tmp_path / "jobs.db"))
    assert result["status"] == "FAILED"
    assert result["events"][-1]["payload"]["error_type"] == "ValidationError"
    if invalid:
        assert agents.calls == ["requirements"]


def test_model_unavailable_is_recorded(tmp_path):
    class Unavailable(FakeAgents):
        def requirements(self, description):
            raise TimeoutError("Local model timed out")
    result = run_job("Build a task management application", Unavailable(), JobStore(tmp_path / "jobs.db"))
    assert result["status"] == "FAILED"
    assert result["events"][-1]["payload"]["error_type"] == "TimeoutError"


@pytest.mark.parametrize("path", ["../secrets", "C:/secrets", "/tmp/code", "app\\code", "app/../code"])
def test_plan_rejects_unsafe_paths(path):
    data = plan()
    data["tasks"][0]["files"] = [path]
    with pytest.raises(ValidationError):
        ImplementationPlan.model_validate(data)


def test_plan_rejects_conflicting_ownership():
    data = plan()
    data["tasks"][1]["files"] = data["tasks"][0]["files"]
    with pytest.raises(ValidationError):
        ImplementationPlan.model_validate(data)
