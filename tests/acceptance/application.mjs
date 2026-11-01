// Trusted declarative HTTP harness. Builders cannot edit this mounted file or contract.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
const {requirements}=JSON.parse(readFileSync('/contract.json','utf8'));
const phase=process.argv[2]==='persistence'?'restart':'functional';
const variables=phase==='restart'?JSON.parse(readFileSync('/tmp/forge-acceptance-vars.json','utf8')):{};
const base='http://127.0.0.1:3000';
function substitute(value){
  if(typeof value==='string'){
    const exact=value.match(/^\{\{([a-z][a-z0-9_]*)\}\}$/);
    if(exact){assert.ok(Object.hasOwn(variables,exact[1]),'Missing captured value');return variables[exact[1]];}
    return value.replace(/\{\{([a-z][a-z0-9_]*)\}\}/g,(_,key)=>{assert.ok(Object.hasOwn(variables,key),'Missing captured value');return String(variables[key]);});
  }
  if(Array.isArray(value))return value.map(substitute);
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,substitute(item)]));
  return value;
}
function subset(actual,expected){
  if(Array.isArray(expected)){
    assert.ok(Array.isArray(actual),'Expected array');
    for(const item of expected)assert.ok(actual.some(candidate=>{try{subset(candidate,item);return true;}catch{return false;}}),'Expected array item is absent');
  }else if(expected&&typeof expected==='object'){
    assert.ok(actual&&typeof actual==='object'&&!Array.isArray(actual),'Expected object');
    for(const [key,value] of Object.entries(expected)){assert.ok(Object.hasOwn(actual,key),`Missing ${key}`);subset(actual[key],value);}
  }else assert.deepEqual(actual,expected);
}
function bind(value,bindings=[]){
  for(const binding of bindings){
    assert.ok(Object.hasOwn(variables,binding.capture),'Missing captured value');
    const parts=binding.pointer.split('/').slice(1).map(key=>key.replace(/~1/g,'/').replace(/~0/g,'~'));
    let parent=value;
    for(const part of parts.slice(0,-1)){assert.ok(parent&&Object.hasOwn(parent,part),'Invalid capture binding');parent=parent[part];}
    const key=parts.at(-1);assert.ok(parent&&Object.hasOwn(parent,key),'Invalid capture binding');
    parent[key]=variables[binding.capture];
  }
  return value;
}
let ready=false;
for(let i=0;i<60;i++){
  try{if((await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok){ready=true;break;}}catch{}
  await new Promise(resolve=>setTimeout(resolve,500));
}
assert.ok(ready,'Application readiness timed out');
if(phase==='functional')for(const page of requirements.pages){
  const response=await fetch(base+page,{redirect:'error',signal:AbortSignal.timeout(5000)});
  assert.equal(response.status,200,`Page ${page} must load`);
  assert.ok(response.headers.get('content-type')?.includes('text/html'),'Pages must return HTML');
  await response.body?.cancel();
}
const scenarios=requirements.scenarios.filter(item=>item.phase===phase);
assert.ok(scenarios.length,'No approved scenarios for this phase');
let steps=0;
for(const scenario of scenarios){
  for(const step of scenario.steps){
    const path=String(substitute(step.path));
    assert.ok(path.startsWith('/')&&!path.startsWith('//')&&!path.includes('..'),'Nonlocal request');
    const response=await fetch(base+path,{method:step.method,redirect:'error',signal:AbortSignal.timeout(5000),
      headers:{'Content-Type':'application/json'},body:step.body_json?JSON.stringify(bind(substitute(JSON.parse(step.body_json)),step.body_bindings)):undefined});
    assert.equal(response.status,step.status,`${scenario.name}: ${step.method} ${path}`);
    const text=await response.text();assert.ok(text.length<=1000000,'Response exceeds acceptance budget');
    let data;
    if(step.expect_json||step.save_as)data=JSON.parse(text);
    if(step.expect_json)subset(data,bind(substitute(JSON.parse(step.expect_json)),step.expect_bindings));
    if(step.contains)assert.ok(text.includes(String(substitute(step.contains))),`${scenario.name}: expected content absent`);
    if(step.save_as){
      const captured=step.save_pointer.split('/').slice(1).reduce((value,key)=>{key=key.replace(/~1/g,'/').replace(/~0/g,'~');assert.ok(value&&Object.hasOwn(value,key),'Invalid capture');return value[key];},data);
      assert.ok(typeof captured==='number'&&Number.isFinite(captured)||typeof captured==='string'&&/^[a-zA-Z0-9_-]{1,64}$/.test(captured),'Capture must be a safe scalar');
      variables[step.save_as]=captured;
    }
    steps++;
  }
  console.log('PASS '+scenario.name);
}
if(phase==='functional')writeFileSync('/tmp/forge-acceptance-vars.json',JSON.stringify(variables));
if(phase==='functional'){
  // Shared protocol policy: concrete JSON POST endpoints reject malformed/non-object input.
  const paths=new Set(scenarios.flatMap(s=>s.steps).filter(s=>s.method==='POST'&&!s.path.includes('{{')).map(s=>s.path));
  for(const path of paths)for(const body of ['{bad','null']){
    const response=await fetch(base+path,{method:'POST',redirect:'error',headers:{'Content-Type':'application/json'},body,signal:AbortSignal.timeout(5000)});
    assert.ok([400,422].includes(response.status),`JSON validation: POST ${path} must reject ${body} with 400/422, got ${response.status}`);
    await response.body?.cancel();
  }
  console.log('PASS shared JSON input validation');
}
console.log(JSON.stringify({phase,scenarios:scenarios.length,steps,browser_interactions:'NOT_TESTED'}));
