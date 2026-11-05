"""Calibrate visit/reload and session facts with real Chromium, without an LLM/app."""
import hashlib
import json
from pathlib import Path
import subprocess
from uuid import uuid4

from forge.browser_capabilities import browser_capabilities


PROJECT=Path(__file__).resolve().parents[1]


def main():
    name='forge-navigation-calibration-'+uuid4().hex[:12]
    directory=PROJECT/'artifacts/navigation-calibration'/uuid4().hex;directory.mkdir(parents=True)
    files=['navigation-calibration.mjs','browser-protocol.mjs']
    command=['docker','run','--rm','--name',name,'--network','none','--read-only',
        '--tmpfs','/tmp:rw,nosuid,size=256m','--shm-size=256m','--cap-drop','ALL',
        '--security-opt','no-new-privileges','--pids-limit','256','--memory','1g','--cpus','2']
    for file in files:command+=['--mount',f'type=bind,src={PROJECT/"tests/acceptance"/file},dst=/checks/{file},readonly']
    command+=['forge-browser-deps:local','node','/checks/navigation-calibration.mjs']
    report={'passed':False,'command':command,'browser_capabilities':browser_capabilities(),
        'harness_sha256':hashlib.sha256(b''.join((PROJECT/'tests/acceptance'/file).read_bytes() for file in files)).hexdigest(),
        'scope':'Trusted browser-protocol calibration only; no generated app or model involved.'}
    try:
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=60)
        rows=[line for line in result.stdout.splitlines() if line.startswith('FORGE_NAVIGATION_CALIBRATION:')]
        if len(rows)==1:report['observed']=json.loads(rows[0].split(':',1)[1])
        report.update(exit_code=result.returncode,output=result.stdout[-4000:],error=result.stderr[-2000:])
        report['passed']=result.returncode==0 and report.get('observed',{}).get('passed') is True
    except (OSError,ValueError,subprocess.SubprocessError) as exc:report['error']=str(exc)[:1500]
    finally:
        try:
            cleanup=subprocess.run(['docker','rm','-f',name],capture_output=True,text=True,encoding='utf-8',timeout=15)
            if cleanup.returncode and 'No such container' not in cleanup.stderr:
                report['passed']=False;report['cleanup_error']=cleanup.stderr[-1000:]
        except (OSError,subprocess.SubprocessError) as exc:report['passed']=False;report['cleanup_error']=str(exc)[:1000]
        path=directory/'report.json';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'report':str(path)}))
    return int(not report['passed'])


if __name__=='__main__':raise SystemExit(main())
