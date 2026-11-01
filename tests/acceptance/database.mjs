// Trusted SQLite inspection after the application server has stopped.
import assert from 'node:assert/strict';
import {existsSync,readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
const {requirements}=JSON.parse(readFileSync('/contract.json','utf8'));
assert.equal(requirements.database,'sqlite');
const file=process.env.SQLITE_PATH;
assert.ok(file&&existsSync(file),'The app must persist to the configured SQLITE_PATH');
const database=new DatabaseSync(file,{readOnly:true});
try{
  const integrity=database.prepare('PRAGMA quick_check').all();
  assert.deepEqual(integrity.map(row=>Object.values(row)[0]),['ok'],'SQLite integrity check failed');
  assert.deepEqual(database.prepare('PRAGMA foreign_key_check').all(),[],'SQLite foreign-key violations exist');
  const tables=database.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").all();
  assert.ok(tables.length,'Application tables must exist');
  let references=0;
  for(const table of tables){
    const name=table.name.replaceAll('"','""');
    references+=database.prepare(`PRAGMA foreign_key_list("${name}")`).all().length;
  }
  const required=requirements.entities.reduce((count,entity)=>count+entity.fields.filter(field=>field.kind==='reference').length,0);
  assert.ok(references>=required,'Declared reference fields require real SQLite foreign keys');
  console.log(JSON.stringify({passed:true,tables:tables.length,declared_foreign_key_columns:references,required_reference_fields:required,integrity:'ok'}));
}finally{database.close();}
