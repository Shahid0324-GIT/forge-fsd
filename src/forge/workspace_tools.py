"""Scoped app tools. The controller binds the workspace/manifest; models cannot change them."""
import hashlib
import json
from pathlib import Path
from typing import Annotated,Literal
from uuid import uuid4

from pydantic import Field,RootModel

from forge.autonomous_planning import AppDraft,manifest_issues
from forge.source_checks import run_source_checks
from forge.tasks import Envelope,TaskConflict
from forge.workspace import is_test_source,safe_path,source_fingerprint,unsupported_imports


PROTECTED={'package.json','package-lock.json','tsconfig.json','next.config.ts','next-env.d.ts'}
SEEDED={'app/layout.tsx','app/globals.css','app/api/health/route.ts',*PROTECTED}


class ListFiles(Envelope):
    tool: Literal['list_files']


class ReadFile(Envelope):
    tool: Literal['read_file']
    path: str = Field(min_length=1,max_length=200)


class WriteFile(ReadFile):
    tool: Literal['write_file']
    content: str = Field(min_length=1,max_length=24000)
    expected_sha256: str | None = Field(pattern=r'^[a-f0-9]{64}$',description='Hash from the latest read; null only when the file does not exist')
    expected_workspace_fingerprint: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')
    require_change: bool = False


class CheckBuild(Envelope):
    tool: Literal['check_build']


class TextEdit(Envelope):
    old: str = Field(min_length=1,max_length=24000)
    new: str = Field(max_length=24000)


class ReplaceText(ReadFile):
    tool: Literal['replace_text']
    edits: list[TextEdit] = Field(min_length=1,max_length=8)
    expected_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_workspace_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')


class ToolCall(RootModel[Annotated[ListFiles | ReadFile | WriteFile | ReplaceText | CheckBuild,Field(discriminator='tool')]]):
    pass


def file_hash(path):return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class WorkspaceTools:
    """Used after the caller authorizes a fixed app workspace and app-owned manifest.

    Each instance is bound to one task dispatch. It cannot grant itself publishing,
    deployment, package installation, or access to another workspace.
    """
    def __init__(self,ledger,state,root,draft,*,workspace_boundary=None,check_runner=run_source_checks):
        boundary=Path(workspace_boundary) if workspace_boundary else Path(__file__).resolve().parents[2]/'workspace'
        self.root=Path(root).absolute()
        if self.root.resolve()==boundary.resolve() or not self.root.resolve().is_relative_to(boundary.resolve()):
            raise ValueError('Tool workspace must be a child of the controller-selected workspace boundary')
        safe_path(self.root,'package.json')
        if not self.root.is_dir():raise ValueError('Tool workspace does not exist')
        self.draft=AppDraft.model_validate(draft)
        issues=manifest_issues(self.draft,self.root)
        if issues:raise ValueError('; '.join(issues))
        self.ledger=ledger;self.state=state;self.check_runner=check_runner
        self.owners={file.path:file.owner for file in self.draft.files}
        self.baseline={path:file_hash(safe_path(self.root,path)) for path in PROTECTED}
        self.directory=ledger.store.path.parent/'tool-calls'/ledger.job_id
        self.directory.mkdir(parents=True,exist_ok=True)

    def _active(self,db=None):
        self.ledger.assert_active(self.state,db)
        if any(file_hash(safe_path(self.root,path))!=digest for path,digest in self.baseline.items()):
            raise TaskConflict('Protected runtime configuration changed; refresh the authorized workspace')

    def describe(self):
        self._active()
        package=safe_path(self.root,'package.json')
        declared=json.loads(package.read_text(encoding='utf-8')) if package.is_file() else {}
        return {'schema':ToolCall.model_json_schema(),'owner':self.state.task.owner,
            'owned_files':[path for path,owner in self.owners.items() if owner==self.state.task.owner],
            'declared_app_dependencies':declared.get('dependencies',{}),
            'declared_dev_dependencies':declared.get('devDependencies',{}),
            'checks_available':['typecheck','production_build'],
            'coverage_not_yet_provided':['browser_interactions','application_acceptance','persistence_restart'],
            'package_installation':False,'host_shell':False}

    def execute(self,request,*,initiator='controller',proposal_call_id=None):
        self._active();call=ToolCall.model_validate(request).root
        call_id=uuid4().hex;report_path=self.directory/(call_id+'.json')
        packet={'call_id':call_id,'job_id':self.ledger.job_id,'task_id':self.state.task.id,
            'parent_task_id':self.state.task.parent_id,'revision':self.state.revision,
            'owner':self.state.task.owner,'request':call.model_dump(),'source_before':source_fingerprint(self.root),
            'phase':'started','initiator':initiator,'proposal_call_id':proposal_call_id}
        report_path.write_text(json.dumps(packet,indent=2),encoding='utf-8')
        event={key:packet[key] for key in ['call_id','task_id','parent_task_id','revision','owner','initiator','proposal_call_id']}
        self.ledger.store.event(self.ledger.job_id,'TOOL_CALL_STARTED',{**event,'tool':call.tool,'report':str(report_path.resolve())},update_status=False)
        try:
            if call.tool=='list_files':
                data={'files':[{'path':path,'owner':self.owners.get(path,'platform'),'exists':safe_path(self.root,path).is_file()}
                    for path in sorted(set(self.owners)|SEEDED)]}
            elif call.tool=='read_file':data=self._read(call.path)
            elif call.tool=='write_file':data=self._write(call,packet,report_path)
            elif call.tool=='replace_text':
                read=self._read(call.path)
                if not read['exists'] or read['sha256']!=call.expected_sha256:raise ValueError('Patch target changed or does not exist; read it again')
                content=read['content']
                for edit in call.edits:
                    matches=content.count(edit.old)
                    if matches!=1:raise ValueError(f'Patch snippet must match exactly once; found {matches} matches. Use actual source and enough surrounding text.')
                    content=content.replace(edit.old,edit.new,1)
                data=self._write(WriteFile(tool='write_file',path=call.path,content=content,
                    expected_sha256=call.expected_sha256,expected_workspace_fingerprint=call.expected_workspace_fingerprint,
                    require_change=True),packet,report_path)
            else:
                report=self.check_runner(self.root,self.ledger.store.path.parent/'source-checks'/self.ledger.job_id,self.ledger.job_id)
                packet['check_report']=report['report']
                self._active()
                data={'passed':report['passed'],'report':report['report'],'coverage':report['coverage'],
                    'source_fingerprint':report['source_fingerprint'],
                    'error':report.get('error',report.get('checks',{}).get('error')),
                    'checks':[{**{key:row.get(key) for key in ['name','exit_code','stopped']},
                        'output':row.get('output','')[:4000],'output_truncated':len(row.get('output',''))>4000}
                        for row in report.get('checks',{}).get('results',[])]}
            packet.update(ok=True,data=data,phase='completed')
        except TaskConflict as exc:
            packet.update(ok=False,error=str(exc),phase='stale')
        except Exception as exc:
            packet.update(ok=False,error=f'{type(exc).__name__}: {exc}',phase='failed')
        packet['source_after']=source_fingerprint(self.root)
        packet['report']=str(report_path.resolve())
        report_path.write_text(json.dumps(packet,indent=2),encoding='utf-8')
        self.ledger.store.event(self.ledger.job_id,'TOOL_CALL_COMPLETED' if packet['ok'] else 'TOOL_CALL_FAILED',
            {**event,'tool':call.tool,'report':packet['report'],'summary':packet.get('error','Tool executed; check scope and results before claiming success.')},update_status=False)
        if packet['phase']=='stale':raise TaskConflict(packet['error'])
        return packet

    def _read(self,relative):
        if relative not in self.owners and relative not in SEEDED:raise PermissionError('Read is outside the declared source and platform files')
        path=safe_path(self.root,relative)
        if not path.is_file():return {'path':relative,'exists':False,'sha256':None,'content':None}
        if path.stat().st_size>24000:raise ValueError('File exceeds the whole-file read budget; request a smaller task rather than silently truncating source')
        raw=path.read_bytes()
        return {'path':relative,'exists':True,'sha256':hashlib.sha256(raw).hexdigest(),'content':raw.decode('utf-8')}

    def _write(self,call,packet,report_path):
        if call.path in PROTECTED:raise PermissionError('Package/runtime configuration is controller-owned')
        if self.owners.get(call.path)!=self.state.task.owner:raise PermissionError('Write is outside task ownership; request a manifest revision from its owner')
        if is_test_source(call.path) and self.state.task.owner!='qa':raise PermissionError('Only QA can edit independent test source')
        if Path(call.path).suffix in {'.ts','.tsx'}:
            rejected=unsupported_imports(self.root,call.path,call.content)
            if rejected:raise ValueError('Dependencies/imports outside available capabilities: '+', '.join(rejected))
        with self.ledger.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._active(db)
            if call.expected_workspace_fingerprint is not None and source_fingerprint(self.root)!=call.expected_workspace_fingerprint:
                raise ValueError('Workspace context changed during generation; inspect fresh references before editing')
            path=safe_path(self.root,call.path)
            if file_hash(path)!=call.expected_sha256:raise ValueError('File changed since it was read; inspect the latest content before editing')
            before=path.read_text(encoding='utf-8') if path.is_file() else None
            if call.require_change and before==call.content:
                raise ValueError('Proposed repair is unchanged source; it cannot resolve the recorded failure. Use the diagnosis to make a substantive correction.')
            packet.update(phase='prepared',before_content=before)
            # Preserve intent and the old source before performing the mutation.
            report_path.write_text(json.dumps(packet,indent=2),encoding='utf-8')
            path.parent.mkdir(parents=True,exist_ok=True)
            safe_path(self.root,call.path).write_text(call.content,encoding='utf-8',newline='\n')
            return {'path':call.path,'sha256':file_hash(path),'bytes':path.stat().st_size}
