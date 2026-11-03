"""Compare an archived incomplete JSON source response with raw-source generation.

Uses the same saved task context. Neither candidate is executed as app code; a trusted
TypeScript parser checks syntax only inside the fixed offline dependency image.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
from uuid import uuid4

from forge.agents import OllamaAgents
from forge.source_checks import PROJECT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace',type=Path,help='Archived SourceEdit model-call JSON containing a TSX file body')
    args=parser.parse_args();original=json.loads(args.trace.read_text(encoding='utf-8'))
    proposal=json.loads(original['output'])
    if not proposal.get('path','').endswith('.tsx') or not isinstance(proposal.get('content'),str):
        parser.error('Choose an archived SourceEdit write containing a TSX file body')
    identity=uuid4().hex;directory=PROJECT/'artifacts/source-transport-evaluation'/identity;directory.mkdir(parents=True)
    print('Evidence: '+str(directory),flush=True)
    (directory/'original.tsx').write_text(json.loads(original['output'])['content'],encoding='utf-8')
    context=json.loads(original['messages'][-1][1]);context['write_target']=proposal['path']
    instruction='''Implement the requested target file from the supplied original request,
review feedback, app design and current source. Return the COMPLETE raw TypeScript/TSX
source file contents only, not JSON, metadata, patches or explanation. A single code
fence is accepted. Preserve requested functionality and supported runtime dependencies.
Choose app-specific types yourself. Interactive hooks require a quoted use client
directive before imports; use HTTP fetch for server routes, never import route modules
into a client page. Finish every function and JSX element. No tool or execution claims.'''
    agents=OllamaAgents('qwen2.5-coder:7b');agents.trace_directory=directory/'model-calls'
    agents.invocation_context={'actor':'source_builder','job_id':identity}
    summary={'passed':False,'original_report':str(args.trace.resolve()),'scope':'Archived response versus raw-source syntax comparison; no generated app execution or correctness claim.'}
    name='forge-source-transport-'+identity[:12];attempted=False
    try:
        content=agents.generate_source(instruction,context)
        summary['model_report']=agents.last_call_identity.get('report')
        (directory/'raw.tsx').write_text(content+'\n',encoding='utf-8')
        image=subprocess.check_output(['docker','image','inspect','forge-task-deps:local','--format','{{.Id}}'],text=True,timeout=15).strip()
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('Expected an immutable existing image')
        code="const fs=require('node:fs'),ts=require('/opt/forge-deps/node_modules/typescript'); const out={}; for(const f of ['original.tsx','raw.tsx']) { const s=ts.createSourceFile(f,fs.readFileSync('/input/'+f,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX); out[f]=s.parseDiagnostics.map(d=>({code:d.code,message:ts.flattenDiagnosticMessageText(d.messageText,' ')})); } console.log(JSON.stringify(out));"
        command=['docker','run','--rm','--name',name,'--pull=never','--network=none','--read-only','--cap-drop=ALL',
            '--security-opt=no-new-privileges','--user=1000:1000','--memory=512m','--pids-limit=64',
            '--mount',f'type=bind,source={directory},target=/input,readonly',image,'node','-e',code]
        summary.update(command=command,image=image);attempted=True
        result=subprocess.run(command,capture_output=True,text=True,timeout=45)
        summary.update(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr)
        if result.returncode==0:
            parsed=json.loads(result.stdout);summary['syntax']=parsed
            summary['passed']=bool(parsed['original.tsx'] and not parsed['raw.tsx'])
    except Exception as exc:summary['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if attempted:
            try:
                cleanup=subprocess.run(['docker','rm','--force',name],capture_output=True,text=True,timeout=15)
                if cleanup.returncode and 'No such container' not in cleanup.stderr:summary['cleanup_error']=cleanup.stderr
            except Exception as exc:summary['cleanup_error']=str(exc)
        if summary.get('cleanup_error'):summary['passed']=False
        (directory/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary),flush=True);return int(not summary['passed'])


if __name__=='__main__':raise SystemExit(main())
