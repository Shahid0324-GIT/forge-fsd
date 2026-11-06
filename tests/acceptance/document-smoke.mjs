import assert from 'node:assert/strict';

// Fixed controller observation. It does not infer app controls or requirements.
export async function checkDocument(page,base){
  const response=await page.goto(base+'/',{waitUntil:'load'});
  assert.ok(response?.ok(),'Homepage did not return a successful document response');
  assert.equal(new URL(page.url()).origin,base,'Homepage left the isolated app origin');
  const body=page.locator('body');
  await body.waitFor({state:'visible'});
  const text=(await body.innerText()).trim();
  const controlsOrMedia=text?0:await page.locator('canvas:visible, img:visible, video:visible, input:visible, select:visible, textarea:visible, button:visible').count();
  assert.ok(text||controlsOrMedia,'Homepage has no visible content');
  return {document_response:true,visible_content:true};
}
