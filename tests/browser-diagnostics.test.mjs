import test from 'node:test';
import assert from 'node:assert/strict';
import {inspectFailure} from './acceptance/browser-diagnostics.mjs';

const page={locator:()=>({ariaSnapshot:async()=>'- heading "Counter: 0"\n- button "Increment"'})};
test('zero matches are reported as a missing target, not a performance timeout',async()=>{
  const step={action:'assert_text',target:{by:'role',value:'status'},value:'0'};
  const evidence=await inspectFailure(page,step,()=>({count:async()=>0}));
  assert.equal(evidence.kind,'missing_target');assert.equal(evidence.match_count,0);
  assert.deepEqual(evidence.target,step.target);assert.equal(evidence.expected,'0');
  assert.match(evidence.accessibility_snapshot,/Counter: 0/);
});
test('text and control values are reported separately without rewriting expectations',async()=>{
  const evidence=await inspectFailure(page,{action:'assert_value',target:{by:'label',value:'Count'},value:'1'},()=>({
    count:async()=>1,isVisible:async()=>true,innerText:async()=>'',inputValue:async()=>'01'}));
  assert.equal(evidence.actual_text,'');assert.equal(evidence.actual_value,'01');assert.equal(evidence.expected,'1');
});
