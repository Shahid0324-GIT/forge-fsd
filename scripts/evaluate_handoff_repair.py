"""Bounded 7B QA -> builder -> trusted test evaluation on a deliberately broken fixture.

No user app is approved, deployed or marked verified by this synthetic evaluation.
Model-generated TypeScript executes only in a network-disabled Docker container.
"""
import json
import subprocess
from pathlib import Path
from uuid import uuid4

from forge.agents import OllamaAgents
from forge.persistence import JobStore
from forge.verification import bounded_command
from forge.workspace import source_fingerprint
import forge.repair as repair

PROJECT = Path(__file__).resolve().parents[1]


def main():
    folder = PROJECT / 'artifacts/handoff-evaluation' / uuid4().hex
    store = JobStore(folder / 'jobs.sqlite3')
    job = store.create({'description': 'Synthetic calculator repair evaluation', 'model': 'qwen2.5-coder:7b'})
    root = folder / 'workspace' / job
    sources = {
        'lib/calculate.ts': 'export function calculate(bill:number,tipPercent:number,people:number){const tip=bill*tipPercent/100;const total=bill+tip;return {tip,total,perPerson:total/(people+1)};}\n',
        'app/api/calculate/route.ts': """import {calculate} from '../../../lib/calculate';
export async function POST(request:Request):Promise<Response>{
  let body:unknown;try{body=await request.json();}catch{return Response.json({error:'Invalid JSON'},{status:400});}
  if(!body||typeof body!=='object'||Array.isArray(body))return Response.json({error:'Invalid input'},{status:400});
  const {bill,tipPercent,people}=body as Record<string,unknown>;
  if(typeof bill!=='number'||!Number.isFinite(bill)||bill<0||typeof tipPercent!=='number'||!Number.isFinite(tipPercent)||tipPercent<0||typeof people!=='number'||!Number.isSafeInteger(people)||people<1)return Response.json({error:'Invalid input'},{status:400});
  return Response.json(calculate(bill,tipPercent,people));
}
""",
        'app/page.tsx': 'export default function Page(){return null;}\n',
    }
    for file, source in sources.items():
        target = root / file; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(source, encoding='utf-8')
    requirements = {'spec_version': 2, 'title': 'Synthetic tip calculator', 'database': 'none', 'pages': ['/'], 'entities': [],
        'acceptance_criteria': ['tip=bill*tipPercent/100; total=bill+tip; perPerson=total/people.', 'Reject negative/nonfinite bill or tipPercent, noninteger or nonpositive people and null/array/malformed JSON with 400.'],
        'scenarios': [{'name': 'Calculate', 'phase': 'functional', 'steps': [{'method': 'POST', 'path': '/api/calculate', 'body_json': '{"bill":100,"tipPercent":10,"people":2}', 'status': 200, 'expect_json': '{"tip":10,"total":110,"perPerson":55}'}]},
                      {'name': 'Invalid', 'phase': 'functional', 'steps': [{'method': 'POST', 'path': '/api/calculate', 'body_json': '{"bill":-1,"tipPercent":10,"people":2}', 'status': 400}]}]}
    plan = {'spec_version': 2, 'framework': 'nextjs-app-router', 'database': 'none', 'routes': ['POST /api/calculate'],
        'tasks': [{'owner': 'frontend', 'objective': 'Show calculator', 'files': ['app/page.tsx'], 'contract': 'Default Page export.'},
                  {'owner': 'backend', 'objective': 'Calculate bill split', 'files': ['lib/calculate.ts', 'app/api/calculate/route.ts'],
                   'contract': 'lib/calculate.ts exports calculate(bill:number,tipPercent:number,people:number):{tip:number,total:number,perPerson:number}. route.ts imports calculate and exports async POST(request:Request):Promise<Response>. Valid input returns 200 JSON; invalid input returns 400.'}],
        'verification': ['build', 'acceptance', 'invalid input']}
    store.event(job, 'PLAN_REVIEW', {'requirements': requirements, 'plan': plan, 'synthetic_fixture': True})
    image = subprocess.check_output(['docker', 'image', 'inspect', 'forge-task-deps:local', '--format', '{{.Id}}'], text=True, timeout=15).strip()
    agents = OllamaAgents('qwen2.5-coder:7b'); agents.trace_directory = folder / 'model-calls'
    repair.PROJECT = folder  # Isolated evaluation process; never points at user app workspaces.
    results = []
    for iteration in range(3):
        name = 'forge-handoff-check-' + uuid4().hex[:12]
        command = ['docker', 'run', '--rm', '--name', name, '--pull=never', '--network=none', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--user=1000:1000', '--memory=1g', '--cpus=2', '--pids-limit=64',
            '--tmpfs', '/work:rw,noexec,nosuid,size=64m,uid=1000,gid=1000',
            '--mount', f'type=bind,source={root},target=/source,readonly',
            '--mount', f'type=bind,source={PROJECT / "tests/acceptance/handoff-repair.mjs"},target=/check.mjs,readonly', image, 'node', '/check.mjs']
        try:execution = bounded_command(command, timeout=45, output_limit=64000)
        finally:subprocess.run(['docker', 'rm', '--force', name], capture_output=True, timeout=15)
        rows = [line.removeprefix('FORGE_HANDOFF:') for line in execution['output'].splitlines() if line.startswith('FORGE_HANDOFF:')]
        outcome = json.loads(rows[-1]) if rows else {'passed': False, 'output': execution['output']}
        passed = outcome.get('passed') is True and execution['exit_code'] == 0 and not execution['stopped']
        results.append({'iteration': iteration, 'execution': execution, 'result': outcome, 'passed': passed})
        print(json.dumps({'iteration': iteration, 'passed': passed, 'result': outcome}), flush=True)
        if passed:
            assert iteration > 0, 'Broken baseline unexpectedly passed'
            break
        path = folder / f'failure-{iteration}.json'
        path.write_text(json.dumps({'source_fingerprint': source_fingerprint(root), 'checks': {'results': [
            {'name': 'synthetic_calculator_checks', 'exit_code': execution['exit_code'] or 1, 'output': execution['output']}]}}), encoding='utf-8')
        store.event(job, 'VERIFICATION_FAILED', {'report': str(path)})
        if iteration == 2:break
        record = repair.repair_job(job, agents, store)
        if record['status'] != 'GENERATED_UNVERIFIED':break
    result = {'job_id': job, 'model': agents.model_name, 'passed': results[-1]['passed'], 'results': results,
              'terminal_status': store.read(job)['status'], 'last_event': store.read(job)['events'][-1],
              'limitations': ['Synthetic planted bug, not autonomous app generation.', 'No production readiness, security or preview approval is implied.'],
              'handoffs': [e['payload'] for e in store.read(job)['events'] if e['status'] == 'AGENT_HANDOFF']}
    (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'passed': result['passed'], 'report': str(folder / 'result.json')}), flush=True)


if __name__ == '__main__':main()
