// Controller-owned build checks. No application-specific routes or database required.
import {spawn} from 'node:child_process';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import ts from '/opt/forge-deps/node_modules/typescript/lib/typescript.js';
import {diagnoseModule} from './framework-diagnostics.mjs';

const results=[];
const digest=path=>createHash('sha256').update(JSON.stringify(JSON.parse(readFileSync(path,'utf8')))).digest('hex');
const sourceLock=digest('/work/package-lock.json');
const imageLock=digest('/opt/forge-deps/package-lock.json');
const diagnostics=ts.sys.readDirectory('/work',['.ts','.tsx'],['node_modules','.next']).flatMap(path=>
  diagnoseModule(ts,path.replace('/work/',''),readFileSync(path,'utf8'))).slice(0,20);
async function check(name,args){
  const started=Date.now();
  const result=await new Promise(resolve=>{
    const child=spawn(process.execPath,args,{cwd:'/work',env:process.env});
    let output='',stopped='';
    const timer=setTimeout(()=>{stopped='timeout';child.kill('SIGKILL');},240000);
    const capture=data=>{
      if(output.length+data.length>64000){stopped='output_limit';child.kill('SIGKILL');return;}
      output+=data.toString();
    };
    child.stdout.on('data',capture);child.stderr.on('data',capture);
    child.on('error',error=>{clearTimeout(timer);resolve({exit_code:null,output,error:String(error),stopped});});
    child.on('close',(code,signal)=>{clearTimeout(timer);resolve({exit_code:code,signal,output,stopped});});
  });
  results.push({name,command:[process.execPath,...args],wall_seconds:(Date.now()-started)/1000,...result});
  return result.exit_code===0&&!result.stopped;
}
let passed=sourceLock===imageLock;
if(passed)passed=await check('typecheck',['/opt/forge-deps/node_modules/typescript/bin/tsc','--noEmit']);
if(passed)passed=await check('production_build',['/opt/forge-deps/node_modules/next/dist/bin/next','build','--webpack']);
console.log('FORGE_SOURCE_REPORT:'+JSON.stringify({passed,results,source_diagnostics:diagnostics,source_lock:sourceLock,image_lock:imageLock,
  error:sourceLock===imageLock?null:'Source and dependency image lockfiles differ',
  coverage:'TypeScript and production build only; application behavior and browser interactions NOT_TESTED'}));
process.exitCode=passed?0:1;
