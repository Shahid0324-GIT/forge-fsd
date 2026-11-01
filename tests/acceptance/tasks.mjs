// Trusted external acceptance harness. Never copied into builder-owned source.
import assert from 'node:assert/strict';
const base = 'http://127.0.0.1:3000';
async function request(path, method='GET', body) {
  const response = await fetch(base + path, {method, headers:{'Content-Type':'application/json'}, body:body === undefined ? undefined : JSON.stringify(body), signal:AbortSignal.timeout(5000)});
  return {status:response.status, value:response.status === 204 ? null : await response.json()};
}
async function ready() {
  for (let i=0; i<60; i++) {
    try { if ((await fetch(base + '/api/health', {signal:AbortSignal.timeout(1000)})).ok) return; } catch {}
    await new Promise(resolve=>setTimeout(resolve,500));
  }
  throw new Error('Application readiness timed out');
}
await ready();
if (process.argv[2] === 'persistence') {
  const list = await request('/api/tasks'); assert.equal(list.status,200);
  const probe = list.value.find(task=>task.title==='Persistence probe');
  assert.ok(probe, 'Task must persist after server restart');
  assert.equal((await request(`/api/tasks/${probe.id}`,'DELETE')).status,204);
  console.log('PASS persistence across process restart');
} else {
  assert.equal((await fetch(base)).status,200, 'Frontend route must load');
  for (const input of [{title:''},{title:'   '},{title:'x'.repeat(121)},{title:'ok',description:'x'.repeat(2001)},{title:'ok',status:'invalid'},{title:'ok',unexpected:true}]) {
    assert.equal((await request('/api/tasks','POST',input)).status,400, `Reject ${JSON.stringify(input).slice(0,80)}`);
  }
  const invalidJson = await fetch(base+'/api/tasks',{method:'POST',body:'{bad',headers:{'Content-Type':'application/json'}});
  assert.equal(invalidJson.status,400);
  const created = await request('/api/tasks','POST',{title:'  Acceptance task  ', description:'Created independently', status:'todo'});
  assert.equal(created.status,201); assert.equal(created.value.title,'Acceptance task');
  assert.ok(Number.isSafeInteger(created.value.id));
  const id=created.value.id;
  const listed=await request('/api/tasks'); assert.equal(listed.status,200);
  assert.ok(listed.value.some(task=>task.id===id));
  const read=await request(`/api/tasks/${id}`); assert.equal(read.status,200); assert.equal(read.value.description,'Created independently');
  assert.ok(!Number.isNaN(Date.parse(read.value.createdAt)));
  assert.ok(!Number.isNaN(Date.parse(read.value.updatedAt)));
  const updated=await request(`/api/tasks/${id}`,'PATCH',{title:'Updated task',status:'done'});
  assert.equal(updated.status,200); assert.equal(updated.value.title,'Updated task'); assert.equal(updated.value.status,'done');
  assert.equal(updated.value.description,'Created independently');
  assert.equal((await request(`/api/tasks/${id}`,'PATCH',{})).status,400);
  assert.equal((await request(`/api/tasks/${id}`,'PATCH',{status:'broken'})).status,400);
  assert.equal((await request(`/api/tasks/${id}`,'DELETE')).status,204);
  for (const method of ['GET','PATCH','DELETE']) assert.equal((await request(`/api/tasks/${id}`,method,method==='PATCH'?{title:'Missing'}:undefined)).status,404);
  assert.equal((await request('/api/tasks/not-an-id')).status,400);
  assert.equal((await request('/api/tasks','POST',{title:'Persistence probe',description:'Survives restart',status:'todo'})).status,201);
  console.log('PASS frontend HTTP smoke, CRUD, validation, missing records, timestamps');
}
