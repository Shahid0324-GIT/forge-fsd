import assert from 'node:assert/strict';
import test from 'node:test';
import {executeStep} from './acceptance/browser-protocol.mjs';

const base='http://forge-browser-app-aaaaaaaaaaaa:3000';
test('navigation stays on the app origin',async()=>{
  const urls=[];const page={goto:async url=>urls.push(url)};
  await executeStep(page,{action:'visit',path:'/calculator'},base);
  assert.deepEqual(urls,[base+'/calculator']);
  await assert.rejects(executeStep(page,{action:'visit',path:'//external.example/'},base));
  assert.equal(urls.length,1);
});
test('semantic locators, values and assertions are interpreted without executing code',async()=>{
  const actions=[];
  const locator={waitFor:async options=>assert.equal(options.state,'visible'),fill:async value=>actions.push(value),inputValue:async()=>'-2.5',innerText:async()=>'Count:   2',count:async()=>0};
  const page={getByLabel:(value,options)=>{assert.equal(value,'Amount');assert.equal(options.exact,true);return locator;},
    getByText:()=>locator,title:async()=>'Calculator'};
  const target={by:'label',value:'Amount'};
  await executeStep(page,{action:'fill',target,value:'-2.5'},base);
  await executeStep(page,{action:'assert_value',target,value:'-2.5'},base);
  await executeStep(page,{action:'assert_text',target,value:'Count: 2'},base);
  await executeStep(page,{action:'assert_count',target,count:0},base);
  await executeStep(page,{action:'assert_title',value:'Calculator'},base);
  assert.deepEqual(actions,['-2.5']);
  await assert.rejects(executeStep(page,{action:'evaluate',target,code:'throw Error()'},base),/Unsupported browser action/);
});

test('hidden matching text cannot satisfy a visible-text assertion',async()=>{
  const page={getByText:()=>({waitFor:async()=>{throw new Error('Element is hidden');},
    innerText:async()=>{throw new Error('Hidden text must not be accepted');}})};
  await assert.rejects(executeStep(page,{action:'assert_text',target:{by:'text',value:'Correct'},value:'Correct'},base),/Element is hidden/);
});
