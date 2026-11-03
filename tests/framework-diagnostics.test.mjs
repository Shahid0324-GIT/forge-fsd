import test from 'node:test';
import assert from 'node:assert/strict';
import ts from '../apps/web/node_modules/typescript/lib/typescript.js';
import {diagnoseModule} from './acceptance/framework-diagnostics.mjs';

test('unquoted directive retains both the syntax and hook diagnosis',()=>{
  const rows=diagnoseModule(ts,'app/page.tsx',"// header\nuse client;\nimport {useState} from 'react';");
  assert.deepEqual(rows.map(row=>row.code),['INVALID_MODULE_DIRECTIVE','CLIENT_HOOK_WITHOUT_DIRECTIVE']);
  assert.equal(rows[0].line,2);assert.match(rows[0].message,/'use client';/);
});
test('valid client code passes but metadata belongs in a server module',()=>{
  const code="'use client';\nimport {useState} from 'react';\n";
  assert.deepEqual(diagnoseModule(ts,'app/page.tsx',code),[]);
  assert.equal(diagnoseModule(ts,'app/page.tsx',code+"export const metadata={title:'Keep me'};")[0].code,'CLIENT_SERVER_METADATA');
  assert.equal(diagnoseModule(ts,'app/page.tsx',code+'export async function generateMetadata(){}')[0].code,'CLIENT_SERVER_METADATA');
  assert.deepEqual(diagnoseModule(ts,'app/layout.tsx',"export const metadata={title:'Keep me'};"),[]);
});
test('comments and ordinary strings are not directives; aliased hooks are detected',()=>{
  const rows=diagnoseModule(ts,'components/Form.tsx',"// use client\nconst message='use client';\nimport {useState as state} from 'react';");
  assert.deepEqual(rows.map(row=>row.code),['CLIENT_HOOK_WITHOUT_DIRECTIVE']);
  assert.equal(diagnoseModule(ts,'app/page.tsx',"import {useState} from 'react';\n'use client';")[0].code,'CLIENT_HOOK_WITHOUT_DIRECTIVE');
});

test('erased type-only imports do not create a false missing-client warning',()=>{
  const code="import type {ReactNode} from 'react';\n'use client';\nimport {useState} from 'react';";
  assert.deepEqual(diagnoseModule(ts,'app/page.tsx',code),[]);
  assert.equal(diagnoseModule(ts,'app/page.tsx',code+"\nexport const metadata={title:'Server only'};")[0].code,'CLIENT_SERVER_METADATA');
});
