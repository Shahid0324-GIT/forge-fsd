// Trusted parser only. Generated modules are input text and are NEVER imported or executed.
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';

const {default:ts}=await import(pathToFileURL(process.argv[2]).href);
let input='';
process.stdin.setEncoding('utf8');
for await (const chunk of process.stdin){
  input+=chunk.toString();
  if(Buffer.byteLength(input)>256000)throw new Error('Parser input limit exceeded');
}
const {file,source}=JSON.parse(input);
if(typeof file!=='string'||typeof source!=='string')throw new Error('Invalid parser input');
const module=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.getScriptKindFromFileName(file));
const diagnostics=module.parseDiagnostics.slice(0,20).map(error=>{
  const position=module.getLineAndCharacterOfPosition(error.start??0);
  return {file,line:position.line+1,column:position.character+1,code:'TS'+error.code,
    message:ts.flattenDiagnosticMessageText(error.messageText,' ').slice(0,1000)};
});
console.log(JSON.stringify({file,source_sha256:createHash('sha256').update(source).digest('hex'),
  parser:'TypeScript '+ts.version,passed:module.parseDiagnostics.length===0,diagnostics,
  diagnostics_truncated:module.parseDiagnostics.length>20,
  scope:'Syntax parsing only. No generated module was executed; types, imports and app behavior remain unverified.'}));
