// Trusted lifecycle only; application code executes in its own internal-network container.
import {spawn} from 'node:child_process';
const next='/opt/forge-deps/node_modules/next/dist/bin/next';
let child;
const expiry=setTimeout(()=>{child?.kill('SIGTERM');setTimeout(()=>process.exit(1),2000);},360000);
function start(args){return spawn(process.execPath,[next,...args],{cwd:'/work',env:process.env,stdio:'inherit'});}
child=start(['build','--webpack']);
child.once('exit',code=>{
  if(code!==0){clearTimeout(expiry);process.exit(code??1);}
  child=start(['start','--hostname','0.0.0.0','--port','3000']);
  child.once('exit',code=>{clearTimeout(expiry);process.exit(code??1);});
});
process.on('SIGTERM',()=>{child?.kill('SIGTERM');setTimeout(()=>process.exit(0),2000);});
