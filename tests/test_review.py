import pytest

from forge.persistence import JobStore
from forge.workflow import resume_job, run_job
from test_workflow import FakeAgents, requirements


def test_approval_survives_restart_and_does_not_call_agents(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    agents = FakeAgents()
    result = run_job("Build a task management application", agents, store)
    decision = {"approved": True, "fingerprint": result["events"][-1]["payload"]["fingerprint"]}
    result = resume_job(result["job_id"], decision, None, JobStore(store.path))
    assert result["status"] == "APPROVED"
    assert agents.calls == ["requirements", "architect"]
    assert [e["status"] for e in result["events"]].count("PLAN_REVIEW") == 1
    with pytest.raises(ValueError):
        resume_job(result["job_id"], decision, None, store)


def test_stale_approval_is_rejected_without_losing_review(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    result = run_job("Build a task management application", FakeAgents(), store)
    with pytest.raises(ValueError, match="Stale approval"):
        resume_job(result["job_id"], {"approved": True, "fingerprint": "0" * 64}, None, store)
    assert store.read(result["job_id"])["status"] == "PLAN_REVIEW"


def test_rejection_cancels_without_building(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    result = run_job("Build a task management application", FakeAgents(), store)
    result = resume_job(result["job_id"], {"approved": False, "fingerprint": result["events"][-1]["payload"]["fingerprint"]}, None, store)
    assert result["status"] == "CANCELLED"


def test_clarification_resume_uses_answers_and_preserves_history(tmp_path):
    class Clarifying(FakeAgents):
        def requirements(self, description):
            self.calls.append("requirements")
            return requirements([] if "human_clarifications" in description else ["Is single-user scope sufficient?"])
    store = JobStore(tmp_path / "jobs.db")
    result = run_job("Build a task management application", Clarifying(), store)
    assert result["status"] == "AWAITING_CLARIFICATION"
    result = resume_job(result["job_id"], {"answers": ["Yes, single-user only"]}, Clarifying(), JobStore(store.path))
    assert result["status"] == "PLAN_REVIEW"
    answered = [e for e in result["events"] if e["status"] == "CLARIFICATION_ANSWERED"]
    assert len(answered) == 1
    assert answered[0]["payload"]["answers"][0]["answer"] == "Yes, single-user only"


def test_clarification_loop_is_bounded(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    agents = FakeAgents(questions=["Confirm scope?"])
    result = run_job("Build a task management application", agents, store)
    for _ in range(2):
        result = resume_job(result["job_id"], {"answers": ["Confirmed"]}, agents, store)
    assert result["status"] == "FAILED"
    assert "round budget" in result["events"][-1]["payload"]["reason"]
    assert agents.calls == ["requirements"] * 3


def test_invalid_answer_does_not_consume_interrupt(tmp_path):
    store = JobStore(tmp_path / "jobs.db")
    result = run_job("Build a task management application", FakeAgents(questions=["Confirm scope?"]), store)
    with pytest.raises(ValueError):
        resume_job(result["job_id"], {"answers": [" "]}, None, store)
    assert store.read(result["job_id"])["status"] == "AWAITING_CLARIFICATION"
