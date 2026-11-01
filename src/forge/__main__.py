import argparse
import json
from pathlib import Path

from forge.persistence import JobStore
from forge.workflow import resume_job, run_job


def main():
    parser = argparse.ArgumentParser(description="ForgeFSD requirements-to-plan vertical slice")
    parser.add_argument("--db", type=Path, default=Path("artifacts/jobs.sqlite3"))
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("plan")
    run.add_argument("description")
    run.add_argument("--model", default="qwen2.5-coder:3b")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("job_id")
    build = commands.add_parser("build")
    build.add_argument("job_id")
    build.add_argument("--model", default="qwen2.5-coder:3b")
    verify = commands.add_parser("verify")
    verify.add_argument("job_id")
    security = commands.add_parser("security")
    security.add_argument("job_id")
    security.add_argument("--model", default="qwen2.5-coder:3b")
    preview = commands.add_parser("preview")
    preview.add_argument("action", choices=["start","stop","status"])
    preview.add_argument("job_id")
    preview.add_argument("--approve", action="store_true")
    report = commands.add_parser("report")
    report.add_argument("job_id")
    report.add_argument("--model", default="qwen2.5-coder:3b")
    repair = commands.add_parser("repair")
    repair.add_argument("job_id")
    repair.add_argument("--model", default="qwen2.5-coder:3b")
    answer = commands.add_parser("answer")
    answer.add_argument("job_id")
    answer.add_argument("--answer", action="append", required=True, dest="answers")
    answer.add_argument("--model", default="qwen2.5-coder:3b")
    for command in ("approve", "reject"):
        decision = commands.add_parser(command)
        decision.add_argument("job_id")
        decision.add_argument("--fingerprint", required=True)
    args = parser.parse_args()
    store = JobStore(args.db)
    if args.command == "inspect":
        result = store.read(args.job_id)
    elif args.command == "report":
        from forge.agents import OllamaAgents
        from forge.reporting import write_report
        result = write_report(args.job_id,OllamaAgents(args.model),store)
    elif args.command == "preview":
        from forge.preview import start_preview, stop_preview, preview_status
        if args.action == "start":
            result = start_preview(args.job_id,store,approved=args.approve)
        elif args.action == "stop":
            result = stop_preview(args.job_id,store)
        else:
            result = preview_status(args.job_id,store)
    elif args.command == "security":
        from forge.agents import OllamaAgents
        from forge.security import security_job
        result = security_job(args.job_id, OllamaAgents(args.model), store)
    elif args.command == "repair":
        from forge.agents import OllamaAgents
        from forge.repair import repair_job
        result = repair_job(args.job_id, OllamaAgents(args.model), store)
    elif args.command == "verify":
        from forge.verification import verify_job
        result = verify_job(args.job_id, store)
    elif args.command == "build":
        from forge.agents import OllamaAgents
        from forge.builders import build_job
        result = build_job(args.job_id, OllamaAgents(args.model), store)
    elif args.command == "plan":
        from forge.agents import OllamaAgents
        result = run_job(args.description, OllamaAgents(args.model), store)
    elif args.command == "answer":
        from forge.agents import OllamaAgents
        result = resume_job(args.job_id, {"answers": args.answers}, OllamaAgents(args.model), store)
    else:
        result = resume_job(args.job_id, {"approved": args.command == "approve", "fingerprint": args.fingerprint}, None, store)
    print(json.dumps(result, indent=2))
    return int(result["status"] in {"FAILED", "VERIFICATION_FAILED", "SECURITY_BLOCKED", "PREVIEW_FAILED"})


if __name__ == "__main__":
    raise SystemExit(main())
