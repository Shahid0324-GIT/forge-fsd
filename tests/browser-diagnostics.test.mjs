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
  assert.equal(evidence.kind,'value_mismatch');
});
test('visible text mismatch identifies rendered text without blaming the event handler',async()=>{
  const evidence=await inspectFailure(page,{action:'assert_text',target:{by:'role',value:'status'},value:'Ready'},()=>({
    count:async()=>1,isVisible:async()=>true,innerText:async()=>'State: Ready',inputValue:async()=>{throw Error('not an input');}}));
  assert.equal(evidence.kind,'text_mismatch');assert.equal(evidence.actual_text,'State: Ready');
  assert.equal(evidence.expected,'Ready');assert.equal(evidence.comparison,'exact_normalized_visible_text');
  assert.match(evidence.guidance,/rendered text/);assert.match(evidence.guidance,/state|handler/);
});
test('whitespace-normalized text that matches is not labelled a text mismatch',async()=>{
  const evidence=await inspectFailure(page,{action:'assert_text',target:{by:'role',value:'status'},value:'Ready now'},()=>({
    count:async()=>1,isVisible:async()=>true,innerText:async()=>' Ready\n now ',inputValue:async()=>null}));
  assert.equal(evidence.kind,'assertion_or_action_failure');
});
