// Trusted calibration fixtures; this is not model-generated application code.
import {DatabaseSync} from 'node:sqlite';
import {spawnSync} from 'node:child_process';
const mode=process.argv[2],file='/tmp/calibration.sqlite';
if(mode!=='missing'){
  const db=new DatabaseSync(file);
  db.exec('PRAGMA foreign_keys=OFF; CREATE TABLE parent(id INTEGER PRIMARY KEY);');
  db.exec(mode==='no_foreign_key'?'CREATE TABLE child(parent_id INTEGER);':'CREATE TABLE child(parent_id INTEGER REFERENCES parent(id));');
  db.exec('INSERT INTO parent VALUES(1);');
  db.exec(`INSERT INTO child VALUES(${mode==='orphan'?99:1});`);
  db.close();
}
const result=spawnSync(process.execPath,['/trusted/database.mjs'],{env:{...process.env,SQLITE_PATH:file},encoding:'utf8',timeout:10000,maxBuffer:64000});
process.stdout.write(result.stdout);process.stderr.write(result.stderr);process.exitCode=result.status??1;
