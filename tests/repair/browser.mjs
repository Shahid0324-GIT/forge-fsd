// Frozen regression assertions. This file is never mounted in the application container.
import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import {chromium} from '/opt/forge-browser/node_modules/playwright/index.mjs';

const base=process.env.FORGE_BROWSER_BASE;
assert.match(base,/^http:\/\/forge-browser-app-[a-f0-9]{12}:3000$/);
const fixture=process.argv[2];
assert.ok(['counter','formatter','client-boundary'].includes(fixture));
const results=[];
let browser;
try{
  let ready=false;
  for(let i=0;i<150;i++){
    try{if((await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok){ready=true;break;}}catch{}
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
  assert.ok(ready,'Application did not become healthy');
  browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  const cases=fixture!=='formatter' ? [
    ['starts_at_zero',async page=>{await page.getByText('Count: 0',{exact:true}).waitFor();}],
    ['increments_by_one',async page=>{
      await page.getByRole('button',{name:'Increment',exact:true}).click();
      await page.getByText('Count: 1',{exact:true}).waitFor();
      await page.getByRole('button',{name:'Increment',exact:true}).click();
      await page.getByText('Count: 2',{exact:true}).waitFor();
    }],
  ] : [
    ['uppercases_name',async page=>{
      await page.getByLabel('Name',{exact:true}).fill('Ada');
      await page.getByRole('button',{name:'Format',exact:true}).click();
      await page.getByText('ADA',{exact:true}).waitFor();
    }],
    ['trims_whitespace',async page=>{
      await page.getByLabel('Name',{exact:true}).fill('  Sam  ');
      await page.getByRole('button',{name:'Format',exact:true}).click();
      await page.getByText('SAM',{exact:true}).waitFor();
    }],
  ];
  if(fixture==='client-boundary')cases.push(
    ['resets_to_zero',async page=>{
      await page.getByRole('button',{name:'Increment',exact:true}).click();
      await page.getByText('Count: 1',{exact:true}).waitFor();
      await page.getByRole('button',{name:'Reset',exact:true}).click();
      await page.getByText('Count: 0',{exact:true}).waitFor();
    }],
    ['preserves_metadata',async page=>{assert.equal(await page.title(),'Counter App');}],
  );
  for(const [name,check] of cases){
    const context=await browser.newContext({serviceWorkers:'block'});
    const page=await context.newPage();page.setDefaultTimeout(4000);
    await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
    const errors=[];page.on('pageerror',error=>errors.push(String(error)));
    try{
      await page.goto(base,{waitUntil:'networkidle',timeout:15000});
      await check(page);assert.deepEqual(errors,[],'Browser runtime errors');
      results.push({name,passed:true});
    }catch(error){
      await page.screenshot({path:`/results/${name}.png`,fullPage:true}).catch(()=>{});
      results.push({name,passed:false,error:String(error),page_text:(await page.locator('body').innerText().catch(()=>'')) .slice(0,1600),runtime_errors:errors});
    }finally{await context.close();}
  }
}catch(error){results.push({name:'setup',passed:false,error:String(error)});}
finally{await browser?.close();}
const report={fixture,passed:results.length===(fixture==='client-boundary'?4:2)&&results.every(row=>row.passed),results};
writeFileSync('/results/browser.json',JSON.stringify(report,null,2));
console.log(JSON.stringify(report));
process.exitCode=report.passed?0:1;
