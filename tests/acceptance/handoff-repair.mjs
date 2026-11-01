// Trusted, fixed checks for a synthetic repair evaluation, not a generated app test plan.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
const compiled=spawnSync(process.execPath,['/opt/forge-deps/node_modules/typescript/bin/tsc',
  '/source/lib/calculate.ts','/source/app/api/calculate/route.ts','--outDir','/work/compiled',
  '--module','commonjs','--target','es2022','--strict','--skipLibCheck','--types','node',
  '--typeRoots','/opt/forge-deps/node_modules/@types'],{timeout:20000,maxBuffer:64000,encoding:'utf8'});
if(compiled.status!==0){console.log('FORGE_HANDOFF:'+JSON.stringify({passed:false,phase:'compile',output:compiled.stdout+compiled.stderr}));process.exit(1);}
try{
  const {POST}=createRequire(import.meta.url)('/work/compiled/app/api/calculate/route.js');
  const request=body=>new Request('http://fixture/api/calculate',{method:'POST',body:JSON.stringify(body),headers:{'Content-Type':'application/json'}});
  let response=await POST(request({bill:100,tipPercent:10,people:2}));
  assert.equal(response.status,200);
  assert.deepEqual(await response.json(),{tip:10,total:110,perPerson:55},'Shared calculate helper must divide total by people');
  response=await POST(request({bill:20,tipPercent:0,people:1}));
  assert.equal(response.status,200);
  assert.deepEqual(await response.json(),{tip:0,total:20,perPerson:20});
  for(const body of [null,[],{bill:-1,tipPercent:10,people:2},{bill:20,tipPercent:-1,people:2},{bill:20,tipPercent:10,people:0},{bill:20,tipPercent:10,people:1.5}]){
    assert.equal((await POST(request(body))).status,400,'Invalid calculator input must return 400');
  }
  console.log('FORGE_HANDOFF:'+JSON.stringify({passed:true,phase:'behavior',assertions:10}));
}catch(error){console.log('FORGE_HANDOFF:'+JSON.stringify({passed:false,phase:'behavior',output:String(error)+'\n'+(error.stack||'')}));process.exitCode=1;}
