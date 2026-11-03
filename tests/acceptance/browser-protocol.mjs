// A fixed interpreter for data-only test contracts. No selectors, scripts or eval.
import assert from 'node:assert/strict';

function target(page,query){
  switch(query.by){
    case 'role': return page.getByRole(query.value,{exact:true,...(query.name?{name:query.name}:{})});
    case 'label': return page.getByLabel(query.value,{exact:true});
    case 'text': return page.getByText(query.value,{exact:true});
    case 'placeholder': return page.getByPlaceholder(query.value,{exact:true});
    default: throw new Error('Unsupported target kind');
  }
}
async function eventually(read,expected){
  const deadline=Date.now()+3500;
  let actual;
  do{
    actual=await read();
    if(actual===expected)return;
    await new Promise(resolve=>setTimeout(resolve,100));
  }while(Date.now()<deadline);
  assert.equal(actual,expected);
}
const visibleText=text=>text.replace(/\s+/g,' ').trim();

export async function executeStep(page,step,base){
  if(step.action==='visit'){
    const url=new URL(step.path,base);
    assert.equal(url.origin,base,'Navigation must stay within the app origin');
    return page.goto(url.href,{waitUntil:'networkidle',timeout:15000});
  }
  if(step.action==='assert_title')return eventually(()=>page.title(),step.value);
  const locator=target(page,step.target);
  switch(step.action){
    case 'click': return locator.click();
    case 'fill': return locator.fill(step.value);
    case 'select': return locator.selectOption(step.value);
    case 'check': return locator.setChecked(step.checked);
    case 'assert_visible': return locator.waitFor({state:'visible'});
    case 'assert_text':
      await locator.waitFor({state:'visible'});
      return eventually(async()=>visibleText(await locator.innerText()),visibleText(step.value));
    case 'assert_value':
      await locator.waitFor({state:'visible'});
      return eventually(()=>locator.inputValue(),step.value);
    case 'assert_count': return eventually(()=>locator.count(),step.count);
    default: throw new Error('Unsupported browser action');
  }
}
