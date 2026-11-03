"""Validate documented native SQLite APIs in the existing fixed image, not app code."""
import json
import re
import subprocess
from uuid import uuid4

from forge.source_checks import PROJECT


PROBE="""const {DatabaseSync}=require('node:sqlite');
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const target=process.env.SQLITE_PATH; fs.mkdirSync(path.dirname(target),{recursive:true});
let db=new DatabaseSync(target); db.exec('CREATE TABLE probe(value TEXT NOT NULL)');
const changed=db.prepare('INSERT INTO probe(value) VALUES (?)').run('ok');
const rows=db.prepare('SELECT value FROM probe WHERE value = ?').all('ok'); db.close();
db=new DatabaseSync(target,{readOnly:true}); const row=db.prepare('SELECT value FROM probe').get();
if(rows.length!==1 || row.value!=='ok' || changed.changes!==1) throw Error('Native SQLite reference probe failed');
console.log(JSON.stringify({node:process.versions.node,row,rows:rows.length,changes:changed.changes,
types_sha256:crypto.createHash('sha256').update(fs.readFileSync('/opt/forge-deps/node_modules/@types/node/sqlite.d.ts')).digest('hex')})); db.close();"""


def main():
    identity=uuid4().hex;directory=PROJECT/'artifacts/runtime-reference-evaluation'/identity;directory.mkdir(parents=True)
    name='forge-runtime-probe-'+identity[:12];attempted=False
    report={'passed':False,'scope':'Trusted runtime API reference check; not a generated-app database test.'}
    try:
        image=subprocess.check_output(['docker','image','inspect','forge-task-deps:local','--format','{{.Id}}'],text=True,timeout=15).strip()
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('Expected an existing immutable dependency image')
        command=['docker','run','--rm','--name',name,'--pull=never','--network=none','--read-only',
            '--cap-drop=ALL','--security-opt=no-new-privileges','--user=1000:1000','--memory=256m','--cpus=1','--pids-limit=64',
            '--tmpfs','/tmp:rw,noexec,nosuid,size=4m,uid=1000,gid=1000','--env','SQLITE_PATH=/tmp/forge-probe/db.sqlite3',image,'node','-e',PROBE]
        report.update(image=image,command=command);attempted=True
        result=subprocess.run(command,capture_output=True,text=True,timeout=45)
        report.update(exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr)
        if result.returncode==0:
            observed=json.loads(result.stdout);report['observed']=observed
            report['passed']=observed['node'].split('.')[0]=='24' and observed['row']=={'value':'ok'} and observed['rows']==1
    except Exception as exc:report['error']=f'{type(exc).__name__}: {exc}'
    finally:
        if attempted:
            try:
                cleanup=subprocess.run(['docker','rm','--force',name],capture_output=True,text=True,timeout=15)
                if cleanup.returncode and 'No such container' not in cleanup.stderr:report['cleanup_error']=cleanup.stderr
            except Exception as exc:report['cleanup_error']=str(exc)
        if report.get('cleanup_error'):report['passed']=False
        (directory/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'report':str(directory/'report.json'),'observed':report.get('observed'),'error':report.get('error')}))
    return int(not report['passed'])


if __name__=='__main__':raise SystemExit(main())
