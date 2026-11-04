// Trusted limited CI smoke. This does not replay frozen browser acceptance.
import assert from 'node:assert/strict';
const base='http://127.0.0.1:3000';
let ready=false;
for(let i=0;i<60;i++){
  try{
    const response=await fetch(base+'/api/health',{redirect:'error',signal:AbortSignal.timeout(1000)});
    ready=response.ok;
    await response.body?.cancel();
    if(ready)break;
  }catch{}
  await new Promise(resolve=>setTimeout(resolve,500));
}
assert.ok(ready,'Application readiness timed out');
const response=await fetch(base+'/',{redirect:'error',signal:AbortSignal.timeout(5000)});
assert.equal(response.status,200,'Homepage must load');
assert.ok(response.headers.get('content-type')?.includes('text/html'),'Homepage must return HTML');
await response.body?.cancel();
console.log(JSON.stringify({scope:'homepage_smoke',pages:1,browser_interactions:'NOT_TESTED',api_scenarios:'NOT_TESTED'}));
