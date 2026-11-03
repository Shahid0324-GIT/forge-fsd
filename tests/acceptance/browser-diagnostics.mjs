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
      }
    }catch(error){result.inspection_error=String(error).slice(0,500);}
  }
  result.accessibility_snapshot=(await page.locator('body').ariaSnapshot().catch(()=>'')).slice(0,1400);
  return result;
}
