// Trusted calibration of runner semantics, never generated application code.
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {chromium} from '/opt/forge-browser/node_modules/playwright/index.mjs';
import {executeStep} from './browser-protocol.mjs';

let requests=0,browser;
const server=createServer((request,response)=>{
  if(request.url!=='/'){response.writeHead(204);response.end();return;}
  requests++;
  response.writeHead(200,{'Content-Type':'text/html','Cache-Control':'no-store'});
  response.end('<!doctype html><title>Navigation calibration</title><script>window.memoryOnly="initial";</script><h1>Navigation calibration</h1>');
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const base=`http://127.0.0.1:${server.address().port}`;
try{
  browser=await chromium.launch({headless:true});
  const context=await browser.newContext({serviceWorkers:'block'});
  assert.deepEqual(await context.cookies(),[]);
  const page=await context.newPage();
  await executeStep(page,{action:'visit',path:'/'},base);
  await page.evaluate(()=>{
    window.memoryOnly='mutated';localStorage.setItem('retained','local');
    sessionStorage.setItem('retained','session');document.cookie='retained=cookie; path=/';
  });
  await executeStep(page,{action:'visit',path:'/'},base);
  const result=await page.evaluate(()=>({memory:window.memoryOnly,local:localStorage.getItem('retained'),
    session:sessionStorage.getItem('retained'),cookie:document.cookie}));
  assert.deepEqual(result,{memory:'initial',local:'local',session:'session',cookie:'retained=cookie'});
  assert.equal(requests,2,'Both visits must request a document');
  await context.close();
  const isolated=await browser.newContext({serviceWorkers:'block'});
  const fresh=await isolated.newPage();
  await executeStep(fresh,{action:'visit',path:'/'},base);
  assert.deepEqual(await fresh.evaluate(()=>({local:localStorage.getItem('retained'),
    session:sessionStorage.getItem('retained'),cookie:document.cookie})),{local:null,session:null,cookie:''});
  assert.equal(requests,3);
  await isolated.close();
  console.log('FORGE_NAVIGATION_CALIBRATION:'+JSON.stringify({passed:true,document_requests:requests,
    memory_reset:true,localStorage_preserved:true,sessionStorage_preserved:true,cookies_preserved:true,fresh_context_isolated:true}));
}finally{
  await browser?.close();
  await new Promise(resolve=>server.close(resolve));
}
