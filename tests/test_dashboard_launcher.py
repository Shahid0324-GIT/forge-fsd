from types import SimpleNamespace

import forge.dashboard as launcher


def test_reopening_launcher_reuses_service_without_creating_manager(monkeypatch):
    class Response:
        headers={'X-ForgeFSD-Control-Plane':'1'}
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr('sys.argv',['forge.dashboard','--no-browser'])
    monkeypatch.setattr(launcher,'urlopen',lambda *_args,**_kwargs:Response())
    monkeypatch.setattr(launcher,'create_app',lambda:(_ for _ in ()).throw(AssertionError('Existing manager must be reused')))
    launcher.main()
