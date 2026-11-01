// Trusted behavior checks for a synthetic title-normalization task.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
const compiled=spawnSync(process.execPath,['/opt/forge-deps/node_modules/typescript/bin/tsc','/source/model.ts','--outDir','/work','--module','commonjs','--target','es2022','--skipLibCheck','--types','node','--typeRoots','/opt/forge-deps/node_modules/@types'],{timeout:15000,maxBuffer:64000,encoding:'utf8'});
if(compiled.status!==0){console.log('FORGE_BENCH:'+JSON.stringify({passed:false,phase:'compile',exit_code:compiled.status,output:compiled.stdout+compiled.stderr}));process.exit(1);}
try{
  const mod=createRequire(import.meta.url)('/work/model.js');
  if(process.argv[2]==='sqlite_repair'){
    assert.deepEqual(Object.keys(mod),['getDb'],'Database adapter must export only getDb');
    const db=mod.getDb();
    assert.equal(typeof db.prepare,'function');
    assert.equal(db.prepare('SELECT 1 AS value').get().value,1);
    assert.equal(mod.getDb(),db,'Reuse the same database instance');
    console.log('FORGE_BENCH:'+JSON.stringify({passed:true,phase:'sqlite_behavior',assertions:4}));
    process.exit(0);
  }
  assert.equal(typeof mod.normalizeTitle,'function','normalizeTitle must be a named export');
  const normalize=mod.normalizeTitle;
  assert.equal(normalize('  hello  '),'hello');
  assert.equal(normalize('\nTask\t'),'Task');
  assert.throws(()=>normalize(''));
  assert.throws(()=>normalize('   '));
  assert.equal(normalize('x'.repeat(120)),'x'.repeat(120));
  assert.throws(()=>normalize('x'.repeat(121)));
  assert.equal(normalize(' '+ 'x'.repeat(120)+' '),'x'.repeat(120));
  assert.equal(normalize(' '.repeat(150)+'x'+' '.repeat(150)),'x');
  console.log('FORGE_BENCH:'+JSON.stringify({passed:true,phase:'behavior',assertions:9}));
}catch(error){console.log('FORGE_BENCH:'+JSON.stringify({passed:false,phase:'behavior',error:String(error)}));process.exitCode=1;}
