"""Local dashboard launcher. Never binds the control plane to a public interface."""
import argparse
import threading
import time
import webbrowser
import socket
from urllib.request import urlopen

import uvicorn

from forge.api import create_app
from forge.builders import PROJECT


def main():
    parser=argparse.ArgumentParser(description='Open the local ForgeFSD agent workspace')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--port',type=int,default=8787)
    args=parser.parse_args()
    if not (1024<=args.port<=65535):parser.error('Port must be between 1024 and 65535')
    if not (PROJECT/'apps/web/dist/index.html').is_file():
        raise SystemExit('Dashboard build is missing. Run npm ci --ignore-scripts and npm run build in apps/web first.')
    url=f'http://127.0.0.1:{args.port}'
    # Reopening the launcher must not create a second manager or interrupt a job.
    try:
        with urlopen(url+'/api/session',timeout=1) as response:
            if response.headers.get('X-ForgeFSD-Control-Plane')=='1':
                print(f'ForgeFSD is already running: {url}',flush=True)
                if not args.no_browser:webbrowser.open(url)
                return
    except Exception:pass
    with socket.socket() as probe:
        probe.settimeout(1)
        if probe.connect_ex(('127.0.0.1',args.port))==0:
            raise SystemExit(f'Port {args.port} is already in use by another service. Choose another --port.')
    if not args.no_browser:
        def open_browser():
            for _ in range(40):
                try:
                    with urlopen(url,timeout=1) as response:
                        if response.status==200:webbrowser.open(url);return
                except Exception:time.sleep(.5)
        threading.Thread(target=open_browser,daemon=True).start()
    print(f'ForgeFSD dashboard: {url}',flush=True)
    app=create_app()
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=args.port,access_log=False,log_level='warning',timeout_graceful_shutdown=5))
    app.state.request_shutdown=lambda:setattr(server,'should_exit',True)
    server.run()


if __name__=='__main__':main()
