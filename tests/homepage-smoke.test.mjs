import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const runner=fileURLToPath(new URL('./acceptance/homepage-smoke.mjs',import.meta.url));
function run(status,contentType){
  const preload=`globalThis.fetch=async url=>{if(!String(url).startsWith('http://127.0.0.1:3000/'))throw Error('Unexpected destination');return new Response('fixture',{status:String(url).endsWith('/api/health')?200:${status},headers:{'content-type':${JSON.stringify(contentType)}}});};`;
  return spawnSync(process.execPath,['--import','data:text/javascript,'+encodeURIComponent(preload),runner],{encoding:'utf8',timeout:5000});
}
test('homepage smoke reports limited coverage for a healthy HTML app',()=>{
  const result=run(200,'text/html');assert.equal(result.status,0,result.stderr);
  const report=JSON.parse(result.stdout);assert.equal(report.scope,'homepage_smoke');assert.equal(report.browser_interactions,'NOT_TESTED');assert.equal(report.api_scenarios,'NOT_TESTED');
});
test('homepage smoke rejects a failing homepage',()=>assert.notEqual(run(500,'text/html').status,0));
test('homepage smoke rejects JSON returned as a homepage',()=>assert.notEqual(run(200,'application/json').status,0));
