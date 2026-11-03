import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {chromium} from '/opt/forge-browser/node_modules/playwright/index.mjs';
import {executeStep} from './browser-protocol.mjs';

const base=process.env.FORGE_BROWSER_BASE;
assert.match(base,/^http:\/\/forge-browser-app-[a-f0-9]{12}:3000$/);
const contract=JSON.parse(readFileSync('/trusted/contract.json','utf8'));
assert.equal(contract.version,1);
const results=[];
let browser;
try{
  let ready=false;
  for(let i=0;i<150;i++){
    try{if((await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok){ready=true;break;}}catch{}
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  assert.ok(ready,'App did not become healthy');
  browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  for(const scenario of contract.suite.scenarios){
    const context=await browser.newContext({serviceWorkers:'block'});
    const page=await context.newPage();page.setDefaultTimeout(3500);
    await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
    const errors=[];page.on('pageerror',error=>errors.push(String(error)));
    let index=0,timer;
    try{
      await Promise.race([
        (async()=>{for(;index<scenario.steps.length;index++)await executeStep(page,scenario.steps[index],base);})(),
        new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Scenario exceeded 25 seconds')),25000);}),
      ]);
      assert.deepEqual(errors,[],'Browser runtime errors');
      results.push({id:scenario.id,passed:true,criteria:scenario.criteria});
    }catch(error){
      await page.screenshot({path:`/results/${scenario.id}.png`,fullPage:true}).catch(()=>{});
      results.push({id:scenario.id,passed:false,criteria:scenario.criteria,step:index+1,
        action:scenario.steps[index]?.action,error:String(error),runtime_errors:errors,
        page_text:(await page.locator('body').innerText().catch(()=>'')).slice(0,2000)});
    }finally{clearTimeout(timer);await context.close();}
  }
}catch(error){results.push({id:'setup',passed:false,error:String(error)});}
finally{await browser?.close();}
const report={passed:results.length===contract.suite.scenarios.length&&results.every(row=>row.passed),results};
writeFileSync('/results/browser.json',JSON.stringify(report,null,2));
console.log(JSON.stringify(report));
process.exitCode=report.passed?0:1;
