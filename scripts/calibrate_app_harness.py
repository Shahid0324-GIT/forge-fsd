"""Check the trusted generic harness against correct and deliberately broken services."""
import json
import subprocess
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]


def main():
    directory=ROOT/'artifacts/general-app-evaluation'
    directory.mkdir(parents=True,exist_ok=True)
    fixtures=json.loads((ROOT/'tests/fixtures/harness-contracts.json').read_text(encoding='utf-8'))
    image=subprocess.check_output(['docker','image','inspect','forge-task-deps:local','--format','{{.Id}}'],text=True,timeout=15).strip()
    rows=[]
    for case,harness in [('calculator','calibrate-application.mjs'),('persistence','calibrate-persistence.mjs')]:
        contract=directory/(case+'-contract.json')
        contract.write_text(json.dumps(fixtures[case]),encoding='utf-8')
        for mode in ['correct','broken']:
            name='forge-calibration-'+uuid4().hex[:12]
            args=['docker','run','--rm','--name',name,'--pull=never','--network=none','--read-only',
                  '--cap-drop=ALL','--security-opt=no-new-privileges','--user=1000:1000',
                  '--memory=256m','--pids-limit=64','--cpus=1','--tmpfs','/tmp:rw,size=16m,uid=1000,gid=1000',
                  '--mount',f'type=bind,source={contract},target=/contract.json,readonly',
                  '--mount',f'type=bind,source={ROOT / "tests/acceptance"},target=/trusted,readonly',
                  image,'node','/trusted/'+harness,mode]
            try:result=subprocess.run(args,capture_output=True,text=True,timeout=45)
            finally:subprocess.run(['docker','rm','--force',name],capture_output=True,timeout=15)
            rows.append({'case':case,'mode':mode,'exit_code':result.returncode,'output':result.stdout+result.stderr})
            print(case,mode,result.returncode,flush=True)
    (directory/'harness-calibration-final.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    if not all((row['exit_code']==0)==(row['mode']=='correct') for row in rows):raise SystemExit('Harness calibration failed')


if __name__=='__main__':main()
