"""Small inference experiment; uses stdlib only and never executes model output."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from urllib.request import Request, urlopen


def object_schema(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
CASES = [
    ("requirements", "A single-user task manager needs create, list, update and delete. "
     "Each task has title, description and status. No authentication or deployment. "
     "Return entity='task', operations using lowercase create/read/update/delete, "
     "fields, assumptions, and acceptance criteria including invalid input and missing records.",
     object_schema({"entity": STRING, "operations": STRINGS, "fields": STRINGS,
                    "assumptions": STRINGS, "acceptance_criteria": STRINGS})),
    ("contract", "Specify a task CRUD HTTP API. Return routes as 'METHOD /path'. "
     "Include exactly GET /api/tasks, POST /api/tasks, GET /api/tasks/{id}, "
     "PATCH /api/tasks/{id}, DELETE /api/tasks/{id}. "
     "Return invalid_input_status=400 and missing_record_status=404. No authentication.",
     object_schema({"routes": STRINGS, "invalid_input_status": {"type": "integer"},
                    "missing_record_status": {"type": "integer"}})),
    ("code", "Write TypeScript export function normalizeTitle(value: string): string. "
     "Trim surrounding whitespace. Throw Error if the trimmed result is empty or longer "
     "than 120 characters. Otherwise return it. The code field must contain the complete "
     "TypeScript function source, not a status code or an example result. "
     "Return code and an explanation. No imports.",
     object_schema({"code": STRING, "explanation": STRING})),
]


def validate(value, schema, path="output"):
    kind = schema["type"]
    expected = {"object": dict, "array": list, "string": str, "integer": int}[kind]
    if type(value) is not expected:
        return [f"{path}: expected {kind}"]
    errors = []
    if kind == "object":
        if set(value) != set(schema["properties"]):
            errors.append(f"{path}: incorrect keys")
        for key, sub in schema["properties"].items():
            if key in value:
                errors.extend(validate(value[key], sub, f"{path}.{key}"))
    elif kind == "array":
        for index, item in enumerate(value):
            errors.extend(validate(item, schema["items"], f"{path}[{index}]"))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="qwen2.5-coder:3b")
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=2)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = Path(__file__).resolve().parents[1] / "artifacts" / "inference" / stamp
    folder.mkdir(parents=True)
    metadata = {"model": args.model, "repeats": args.repeats,
                "note": "First call may include cold model load; no forced unload."}
    for endpoint in ("version", "tags"):
        try:
            with urlopen(f"http://127.0.0.1:11434/api/{endpoint}", timeout=10) as response:
                metadata[endpoint] = json.load(response)
        except Exception as exc:
            metadata[endpoint] = {"error": str(exc)}
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    results = []
    for repeat in range(args.repeats):
        for name, prompt, schema in CASES:
            payload = {"model": args.model, "stream": False, "format": schema,
                       "messages": [{"role": "system", "content": "You are a software engineer. Fulfill the user's task. Return only JSON matching the provided schema. When asked for code, write the full implementation as a JSON string."},
                                    {"role": "user", "content": prompt + "\nSchema: " + json.dumps(schema)}],
                       "options": {"temperature": 0, "seed": 42 + repeat,
                                   "num_ctx": 4096, "num_predict": 768}, "keep_alive": "10m"}
            row = {"case": name, "repeat": repeat + 1, "request": payload,
                   "timestamp": datetime.now(timezone.utc).isoformat()}
            started = perf_counter()
            try:
                req = Request("http://127.0.0.1:11434/api/chat", json.dumps(payload).encode(),
                              {"Content-Type": "application/json"})
                with urlopen(req, timeout=240) as response:
                    raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("Response exceeds output budget")
                body = json.loads(raw)
                row["response"] = body
                value = json.loads(body["message"]["content"])
                errors = validate(value, schema)
                row["schema_errors"] = errors
                row["completed"] = body.get("done") is True and body.get("done_reason") == "stop"
                if name == "requirements" and not errors:
                    row["contract_checks_passed"] = value["entity"] == "task" and set(value["operations"]) == {"create", "read", "update", "delete"}
                elif name == "contract" and not errors:
                    row["contract_checks_passed"] = set(value["routes"]) == {"GET /api/tasks", "POST /api/tasks", "GET /api/tasks/{id}", "PATCH /api/tasks/{id}", "DELETE /api/tasks/{id}"} and value["invalid_input_status"] == 400 and value["missing_record_status"] == 404
                elif name == "code" and not errors:
                    row["code_shape_passed"] = all(part in value["code"] for part in ("export function normalizeTitle", ".trim()", "throw", "120", "return"))
                row["code_execution"] = "NOT_EXECUTED"
                duration = body.get("eval_duration", 0)
                row["tokens_per_second"] = round(body.get("eval_count", 0) / (duration / 1e9), 2) if duration else None
            except Exception as exc:
                row["error"] = str(exc)
            row["wall_seconds"] = round(perf_counter() - started, 2)
            results.append(row)
            (folder / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(json.dumps({k: v for k, v in row.items() if k not in {"request", "response"}}), flush=True)
    print(f"Evidence: {folder / 'results.json'}", flush=True)
    return int(any(r.get("error") or r.get("schema_errors") or not r.get("completed") or r.get("contract_checks_passed") is False or r.get("code_shape_passed") is False for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
