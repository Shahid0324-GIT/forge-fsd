import assert from 'node:assert/strict';
import test from 'node:test';
import {checkDocument} from './acceptance/document-smoke.mjs';

const base='http://forge-browser-app-0123456789ab:3000';
function page({ok=true,text='My app',origin=base,media=0}={}){
  return {goto:async()=>({ok:()=>ok}),url:()=>origin+'/',
    locator:()=>({waitFor:async()=>{},innerText:async()=>text,count:async()=>media})};
}
test('startup verifies a real successful response and visible content',async()=>{
  assert.deepEqual(await checkDocument(page(),base),{document_response:true,visible_content:true});
});
test('startup accepts visible controls or media without imposing text markup',async()=>{
  assert.deepEqual(await checkDocument(page({text:'',media:1}),base),{document_response:true,visible_content:true});
});
for(const [name,options] of [['HTTP failure',{ok:false}],['blank page',{text:'  '}],['external redirect',{origin:'https://example.com'}]]){
  test(`startup rejects ${name}`,async()=>{await assert.rejects(checkDocument(page(options),base));});
}
