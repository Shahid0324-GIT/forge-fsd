// Fixed, controller-owned profile. No model-provided selectors, scripts, URLs or commands.
import assert from 'node:assert/strict';
import {writeFileSync} from 'node:fs';
import {chromium} from '/opt/forge-browser/node_modules/playwright/index.mjs';

const base=process.env.FORGE_BROWSER_BASE;
assert.match(base,/^http:\/\/forge-browser-app-[a-f0-9]{12}:3000$/);
const profile='temperature-converter-v1';
const results=[];
let browser;
let ready=false;
for(let i=0;i<150;i++){
  try{if((await fetch(base+'/api/health',{signal:AbortSignal.timeout(1000)})).ok){ready=true;break;}}catch{}
  await new Promise(resolve=>setTimeout(resolve,1000));
}
try{
  assert.ok(ready,'Application did not become healthy');
  // The outer container is non-root, network-isolated and has no host credentials.
  // Chromium's process sandbox is unavailable under this restricted Docker setup.
  browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']});
  async function check(name,run){
    const context=await browser.newContext({serviceWorkers:'block'});
    const page=await context.newPage();
    page.setDefaultTimeout(7000);
    await context.route('**/*',route=>new URL(route.request().url()).origin===base?route.continue():route.abort());
    const started=Date.now();
    try{
      await page.goto(base,{waitUntil:'networkidle',timeout:15000});
      await run(page);
      results.push({name,passed:true,wall_seconds:(Date.now()-started)/1000});
    }catch(error){
      const screenshot=`${name}.png`;
      await page.screenshot({path:'/results/'+screenshot,fullPage:true}).catch(()=>{});
      results.push({name,passed:false,error:String(error),screenshot,wall_seconds:(Date.now()-started)/1000});
    }finally{await context.close();}
  }
  const value=page=>page.getByLabel('Value:',{exact:true});
  const unit=page=>page.getByLabel('From:',{exact:true});
  const convert=page=>page.getByRole('button',{name:'Convert',exact:true});
  async function calculate(page,input,from,expected){
    await value(page).fill(input);await unit(page).selectOption(from);await convert(page).click();
    await page.getByText(expected,{exact:true}).waitFor({state:'visible'});
  }
  await check('celsius_to_fahrenheit',page=>calculate(page,'0','C','Result: 32.00 F'));
  await check('fahrenheit_to_celsius',page=>calculate(page,'212','F','Result: 100.00 C'));
  await check('negative_and_decimal_values',async page=>{
    await calculate(page,'-40','C','Result: -40.00 F');
    await calculate(page,'36.5','C','Result: 97.70 F');
    await calculate(page,'99.5','F','Result: 37.50 C');
  });
  await check('source_unit_does_not_relabel_result',async page=>{
    await calculate(page,'36.5','C','Result: 97.70 F');await unit(page).selectOption('F');
    const shown=await page.getByText(/^Result:/).allTextContents();
    assert.ok(shown.length===0||(shown.length===1&&shown[0].trim()==='Result: 97.70 F'),'Previous result was relabeled without recalculation');
  });
  await check('changed_value_clears_previous_result',async page=>{
    await calculate(page,'36.5','C','Result: 97.70 F');await value(page).fill('20');
    assert.equal(await page.getByText(/^Result:/).count(),0,'A previous result remained after changing the input');
  });
  await check('empty_input_blocks_submission',async page=>{
    await calculate(page,'0','C','Result: 32.00 F');await value(page).fill('');await convert(page).click();
    assert.equal(await value(page).evaluate(el=>el.validity.valueMissing),true);
    assert.equal(await page.getByText(/^Result:/).count(),0);
  });
  await check('extra_decimal_precision',page=>calculate(page,'36.567','C','Result: 97.82 F'));
  await check('mocked_api_error_is_visible',async page=>{
    await page.route('**/api/convert',route=>route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'Rejected by browser test'})}));
    await value(page).fill('10');await convert(page).click();
    await page.getByText('Rejected by browser test',{exact:true}).waitFor({state:'visible'});
  });
}catch(error){results.push({name:'browser_setup',passed:false,error:String(error)});}
finally{await browser?.close();}
const report={profile,browser:'Chromium',passed:results.length===8&&results.every(r=>r.passed),results,
  limitations:['Fixed converter profile, not general generated-app browser coverage.','Error-display case mocks one local API response; other conversions use the real application.','Chromium process sandbox disabled inside a restricted non-root Docker container.']};
writeFileSync('/results/browser.json',JSON.stringify(report,null,2));
console.log('FORGE_BROWSER:'+JSON.stringify(report));
process.exitCode=report.passed?0:1;
