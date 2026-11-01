// Trusted lifecycle wrapper: no shell commands or model-provided arguments.
import { spawn } from 'node:child_process';
const executable='/opt/forge-deps/node_modules/next/dist/bin/next';
let child;
const expiry=setTimeout(()=>{child?.kill('SIGTERM');setTimeout(()=>process.exit(0),2000);},30*60*1000);
function launch(args) { return spawn(process.execPath,[executable,...args],{cwd:'/work',env:process.env,stdio:'inherit'}); }
child=launch(['build','--webpack']);
const buildTimeout=setTimeout(()=>{child.kill('SIGKILL');process.exitCode=1;},240000);
child.once('exit',code=>{
  clearTimeout(buildTimeout);
  if(code!==0){clearTimeout(expiry);process.exit(code??1);}
  child=launch(['start','--hostname','0.0.0.0','--port','3000']);
  child.once('exit',code=>{clearTimeout(expiry);process.exit(code??1);});
});
process.on('SIGTERM',()=>{child?.kill('SIGTERM');setTimeout(()=>process.exit(0),2000);});
