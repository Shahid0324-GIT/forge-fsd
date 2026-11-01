"""Exercise the trusted SQLite gate with correct, orphaned, missing-FK and absent databases."""
import json
import subprocess
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]


def main():
    image=subprocess.check_output(['docker','image','inspect','forge-task-deps:local','--format','{{.Id}}'],text=True,timeout=15).strip()
    results=[]
    for case in ['correct','orphan','no_foreign_key','missing']:
        name='forge-db-calibration-'+uuid4().hex[:12]
        args=['docker','run','--rm','--name',name,'--pull=never','--network=none','--read-only',
              '--cap-drop=ALL','--security-opt=no-new-privileges','--user=1000:1000','--memory=256m','--cpus=1','--pids-limit=64',
              '--tmpfs','/tmp:rw,size=16m,uid=1000,gid=1000',
              '--mount',f'type=bind,source={ROOT / "tests/acceptance"},target=/trusted,readonly',
              '--mount',f'type=bind,source={ROOT / "tests/fixtures/database-contract.json"},target=/contract.json,readonly',
              image,'node','/trusted/calibrate-database.mjs',case]
        try:result=subprocess.run(args,capture_output=True,text=True,timeout=35)
        finally:subprocess.run(['docker','rm','--force',name],capture_output=True,timeout=15)
        results.append({'case':case,'exit_code':result.returncode,'output':result.stdout+result.stderr})
        print(case,result.returncode,flush=True)
    directory=ROOT/'artifacts/general-app-evaluation';directory.mkdir(exist_ok=True)
    (directory/'database-gate-calibration.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    if not all((row['exit_code']==0)==(row['case']=='correct') for row in results):raise SystemExit('Database calibration failed')


if __name__=='__main__':main()
