// Read-only facts about a failed browser action, not a model's diagnosis.
export async function inspectFailure(page,step,locate){
  const result={expected:step?.value??step?.count??null};
  if(step?.target){
    result.target=step.target;
    try{
      const locator=locate(page,step.target);result.match_count=await locator.count();
      if(result.match_count===0){
        result.kind='missing_target';
        if(step.target.by==='role')result.required_semantics={role:step.target.value,accessible_name:step.target.name||null,
          guidance:'Expose the expected semantic HTML role or matching role attribute on the intended visible app element; preserve the value and behavior.'};
        result.guidance='No element matches the frozen semantic target. Inspect app markup/accessibility; this is not evidence of slow performance. Do not increase test timeouts.';
      }else if(result.match_count>1){
        result.kind='ambiguous_target';result.guidance='Multiple elements match the frozen target; inspect accessible controls and names.';
      }else{
        result.visible=await locator.isVisible();
        result.kind=result.visible?'assertion_or_action_failure':'hidden_target';
        result.actual_text=await locator.innerText().catch(()=>null);
        result.actual_value=await locator.inputValue().catch(()=>null);
        const normalized=text=>text.replace(/\s+/g,' ').trim();
        if(result.visible && step.action==='assert_text' && typeof result.actual_text==='string'
          && normalized(result.actual_text)!==normalized(step.value)){
          result.kind='text_mismatch';result.comparison='exact_normalized_visible_text';
          result.guidance='The target exists and is visible. Its rendered text differs from the expected text. Inspect the JSX content and which element carries the target role before changing state arithmetic or event handlers. Extra labels or prefixes are part of innerText; aria-label does not replace rendered text. Preserve frozen assertions.';
        }else if(result.visible && step.action==='assert_value' && result.actual_value!==null && result.actual_value!==step.value){
          result.kind='value_mismatch';result.comparison='exact_input_value';
          result.guidance='The visible input value differs from the expected value. Inspect the controlled value and input updates; visible labels and surrounding text are not the input value. Preserve frozen assertions.';
        }
      }
    }catch(error){result.inspection_error=String(error).slice(0,500);}
  }
  result.accessibility_snapshot=(await page.locator('body').ariaSnapshot().catch(()=>'')).slice(0,1400);
  return result;
}
