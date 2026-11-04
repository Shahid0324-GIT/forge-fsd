// Trusted verification controller; generated source cannot modify this mount.
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
const results = [];
const contract=process.env.FORGE_APP_CONTRACT?JSON.parse(readFileSync(process.env.FORGE_APP_CONTRACT,'utf8')):null;
const smokeOnly=contract?.verification_scope==='build-homepage-smoke';
if (smokeOnly && (contract.requirements.database!=='none' || contract.requirements.scenarios.length)) throw new Error('Homepage smoke scope requires a stateless contract with no API scenarios');
const harness=smokeOnly?'/trusted/homepage-smoke.mjs':contract?'/trusted/application.mjs':'/trusted/tasks.mjs';
async function check(name, args, timeout=240000) {
  const started = Date.now();
  const result = await new Promise(resolve => {
    const child = spawn(process.execPath, args, {cwd:'/work', env:process.env});
    let output = '', stopped = '';
    const timer = setTimeout(()=>{stopped='timeout';child.kill('SIGKILL');},timeout);
    const capture = data => {
      if (output.length + data.length > 64000) { stopped='output_limit';child.kill('SIGKILL'); return; }
      output += data.toString();
    };
    child.stdout.on('data',capture);child.stderr.on('data',capture);
    child.on('error',error=>{clearTimeout(timer);resolve({exit_code:null,error:String(error),output});});
    child.on('close',(code,signal)=>{clearTimeout(timer);resolve({exit_code:code,signal,stopped,output});});
  });
  const row = {name, command:[process.execPath,...args], wall_seconds:(Date.now()-started)/1000,...result};
  if(row.exit_code!==0)row.platform_reference=readFileSync('/trusted/platform-reference.txt','utf8');
  results.push(row);
  return row.exit_code === 0 && !row.stopped;
}
function startServer() {
  const child = spawn(process.execPath,['/opt/forge-deps/node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','3000'],{cwd:'/work',env:process.env,stdio:['ignore','ignore','ignore']});
  return child;
}
async function stopServer(child) {
  if (child.exitCode !== null) return;
  await new Promise(resolve=>{const timer=setTimeout(()=>{child.kill('SIGKILL');resolve();},3000);child.once('close',()=>{clearTimeout(timer);resolve();});child.kill('SIGTERM');});
}
let passed = await check('typecheck',['/opt/forge-deps/node_modules/typescript/bin/tsc','--noEmit']);
if (passed) passed = await check('production_build',['/opt/forge-deps/node_modules/next/dist/bin/next','build','--webpack']);
if (passed) {
  let server=startServer();
  try { passed = await check(smokeOnly?'homepage_smoke':'acceptance',[harness],120000); }
  finally { await stopServer(server); }
  if (passed && (!contract || contract.requirements.scenarios.some(item=>item.phase==='restart'))) {
    server=startServer();
    try { passed = await check('persistence_restart',[harness,'persistence'],120000); }
    finally { await stopServer(server); }
  }
}
if(passed&&contract?.requirements.database==='sqlite')passed=await check('database_integrity',['/trusted/database.mjs'],30000);
console.log('FORGE_REPORT:' + JSON.stringify({passed, results, dependency_lock:JSON.parse(readFileSync('/opt/forge-deps/package-lock.json','utf8')).lockfileVersion}));
process.exitCode = passed ? 0 : 1;
