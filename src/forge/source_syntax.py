"""Parse each generated TypeScript module before delegating dependent source tasks."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4

from forge.tasks import TaskBlockedError
from forge.workspace import safe_path


PROJECT=Path(__file__).resolve().parents[2]
HARNESS=Path(__file__).with_suffix('.mjs')
TYPESCRIPT=PROJECT/'apps/web/node_modules/typescript/lib/typescript.js'


def ensure_parser():
    node=shutil.which('node')
    if not node or not TYPESCRIPT.is_file() or not HARNESS.is_file():
        raise TaskBlockedError('The trusted TypeScript parser is unavailable. Restore the existing dashboard development dependencies before source generation; no app defect inferred.')
    return node


def run_source_syntax(root,relative,directory,job_id):
    if not re.fullmatch(r'[a-f0-9]{32}',job_id):raise ValueError('Invalid job identity')
    path=safe_path(Path(root),relative);raw=path.read_bytes();source=raw.decode('utf-8')
    digest=hashlib.sha256(raw).hexdigest()
    harness=hashlib.sha256(HARNESS.read_bytes()).hexdigest()
    if path.suffix not in {'.ts','.tsx'}:
        report={'file':relative,'passed':True,'source_sha256':digest,'applicable':False,
            'diagnostics':[],'scope':'Not a TypeScript module; no syntax claim for this format.'}
    else:
        try:
            result=subprocess.run([ensure_parser(),str(HARNESS),str(TYPESCRIPT)],
                input=json.dumps({'file':relative,'source':source},ensure_ascii=False),
                text=True,encoding='utf-8',capture_output=True,timeout=20)
            if result.returncode or len(result.stdout)>64000:raise ValueError('Trusted parser did not produce a bounded report')
            report=json.loads(result.stdout)
            if report.get('file')!=relative or report.get('source_sha256')!=digest or type(report.get('passed')) is not bool:
                raise ValueError('Parser report does not belong to the current module')
            report['applicable']=True
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            raise TaskBlockedError('Source parser could not produce trustworthy evidence: '+str(exc)[:500]) from exc
    if (hashlib.sha256(path.read_bytes()).hexdigest()!=digest
        or hashlib.sha256(HARNESS.read_bytes()).hexdigest()!=harness):
        raise ValueError('Source or syntax harness changed during parsing; retrieve fresh evidence')
    report.update(job_id=job_id,harness_sha256=harness)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    output=directory/(uuid4().hex+'.json');report['report']=str(output.resolve())
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
