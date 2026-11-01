"""Small local model comparison; generated TypeScript executes only inside Docker."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime,timezone
from pathlib import Path
from time import perf_counter
from urllib.request import Request,urlopen
from uuid import uuid4

from benchmark_ollama import CASES,STRING,object_schema,validate
from forge.verification import bounded_command


ROOT=Path(__file__).resolve().parents[1]
REPAIR=('repair',
    'Repair this exported TypeScript function. It must trim whitespace BEFORE validation, '
    'reject an empty trimmed title and reject a trimmed title longer than 120 characters. '
    'Return the trimmed title otherwise. Preserve its named export and signature. '
    'Broken source: export function normalizeTitle(value: string): string { '
    'if (value.length > 120) throw new Error("too long"); return value; } '
    'Return full corrected TypeScript in code and a short explanation.',
    object_schema({'code':STRING,'explanation':STRING}))
SQLITE_REPAIR=('sqlite_repair',
    'Repair this Node 24 TypeScript database adapter using the built-in node:sqlite API. '
    'Export ONLY getDb(): DatabaseSync. It must return the same usable DatabaseSync instance '
    'on repeated calls. Do not add task CRUD functions. Remove unsupported finalize() calls. '
    'Use an in-memory database. Broken source: import { DatabaseSync } from "node:sqlite"; '
    'const db = new DatabaseSync(":memory:"); export function getDb(): DatabaseSync { '
    'const stmt=db.prepare("SELECT 1"); stmt.finalize(); return db; } '
    'export function createTask(title:string) { return title; } '
    'Return the full corrected adapter in code and a short explanation.',
    object_schema({'code':STRING,'explanation':STRING}))


def call(endpoint,data=None,timeout=240):
    request=Request('http://127.0.0.1:11434/api/'+endpoint,
                    None if data is None else json.dumps(data).encode(),
                    {'Content-Type':'application/json'})
    with urlopen(request,timeout=timeout) as response:
        raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('Model response exceeds budget')
    return json.loads(raw)


def execute_code(code,directory,image,case):
    directory.mkdir(parents=True)
    (directory/'model.ts').write_text(code,encoding='utf-8')
    name='forge-model-check-'+uuid4().hex[:12]
    command=['docker','run','--rm','--name',name,'--pull=never','--network=none',
             '--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--user=1000:1000',
             '--memory=512m','--cpus=1','--pids-limit=64','--tmpfs','/work:rw,size=32m,uid=1000,gid=1000',
             '--mount',f'type=bind,source={directory},target=/source,readonly',
             '--mount',f'type=bind,source={ROOT / "tests/acceptance/model-function.mjs"},target=/check.mjs,readonly',
             image,'node','/check.mjs',case]
    try:
        execution=bounded_command(command,timeout=35,output_limit=100000)
        rows=[line[len('FORGE_BENCH:'):] for line in execution['output'].splitlines() if line.startswith('FORGE_BENCH:')]
        result=json.loads(rows[-1]) if rows else {'passed':False,'error':'No harness result'}
        return {'execution':execution,'result':result,'passed':execution['exit_code']==0 and not execution['stopped'] and result.get('passed') is True}
    finally:subprocess.run(['docker','rm','--force',name],capture_output=True,timeout=15)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models',nargs='+',default=['qwen2.5-coder:3b','qwen2.5-coder:7b'])
    parser.add_argument('--repeats',type=int,choices=[1,2],default=2)
    args=parser.parse_args()
    folder=ROOT/'artifacts/model-comparison'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    image=subprocess.check_output(['docker','image','inspect','forge-task-deps:local','--format','{{.Id}}'],text=True,timeout=15).strip()
    tags=call('tags');installed={model['name'] for model in tags['models']}
    if any(model not in installed for model in args.models):raise SystemExit('Install all selected models before comparison')
    metadata={'timestamp':datetime.now(timezone.utc).isoformat(),'models':args.models,'repeats':args.repeats,
              'ollama':call('version'),'installed_models':tags,'execution_image':image,
              'harness_sha256':hashlib.sha256((ROOT/'tests/acceptance/model-function.mjs').read_bytes()).hexdigest(),
              'limits':{'context':4096,'output_tokens':1200,'client_timeout_seconds':240},
              'limitations':['Small fixed benchmark, not proof of general reliability or security.',
                  'Greedy repeated responses are not independent statistical samples.',
                  'Requirements checks cover selected fields only, not complete semantic correctness.',
                  'Each model is unloaded before its group; cold and warm timings are both retained.']}
    (folder/'metadata.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    results=[]
    for model in args.models:
        # Release any selected model before loading this candidate; do not delete weights.
        for selected in args.models:call('generate',{'model':selected,'keep_alive':0},timeout=60)
        for repeat in range(args.repeats):
            for name,prompt,schema in [*CASES,REPAIR,SQLITE_REPAIR]:
                request={'model':model,'stream':False,'format':schema,
                    'messages':[{'role':'system','content':'You are a software engineer. Fulfill the task and return JSON matching the schema. Code fields contain complete source, never an example result.'},
                                {'role':'user','content':prompt+'\nSchema: '+json.dumps(schema)}],
                    'options':{'temperature':0,'seed':42+repeat,'num_ctx':4096,'num_predict':1200},'keep_alive':'10m'}
                row={'model':model,'case':name,'repeat':repeat+1,'request':request,'timestamp':datetime.now(timezone.utc).isoformat()}
                started=perf_counter()
                try:
                    response=call('chat',request)
                    row['wall_seconds']=round(perf_counter()-started,2)
                    row['response']=response
                    data=json.loads(response['message']['content']);errors=validate(data,schema)
                    row['schema_errors']=errors
                    row['completed']=response.get('done') is True and response.get('done_reason')=='stop'
                    passed=not errors and row['completed']
                    if passed and name=='requirements':
                        passed=data['entity']=='task' and set(data['operations'])=={'create','read','update','delete'} and {'title','description','status'}.issubset(data['fields'])
                    elif passed and name=='contract':
                        passed=set(data['routes'])=={'GET /api/tasks','POST /api/tasks','GET /api/tasks/{id}','PATCH /api/tasks/{id}','DELETE /api/tasks/{id}'} and data['invalid_input_status']==400 and data['missing_record_status']==404
                    elif passed and name in {'code','repair','sqlite_repair'}:
                        row['code_check']=execute_code(data['code'],folder/(model.replace(':','-')+f'-{name}-{repeat+1}'),image,name)
                        passed=row['code_check']['passed']
                    row['passed']=passed
                    duration=response.get('eval_duration',0)
                    row['tokens_per_second']=round(response.get('eval_count',0)/(duration/1e9),2) if duration else None
                    row['placement']=call('ps')
                except Exception as exc:
                    row.update(passed=False,error=str(exc),wall_seconds=round(perf_counter()-started,2))
                results.append(row)
                (folder/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
                print(json.dumps({key:row.get(key) for key in ['model','case','repeat','passed','wall_seconds','tokens_per_second','error']}),flush=True)
        call('generate',{'model':model,'keep_alive':0},timeout=60)
    summary={model:{'passed':sum(row['passed'] for row in results if row['model']==model),
                    'total':sum(row['model']==model for row in results),
                    'behavior_passed':sum(row['passed'] for row in results if row['model']==model and row['case'] in {'code','repair','sqlite_repair'}),
                    'behavior_total':sum(row['model']==model and row['case'] in {'code','repair','sqlite_repair'} for row in results)} for model in args.models}
    (folder/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True);print('Evidence: '+str(folder),flush=True)


if __name__=='__main__':main()
