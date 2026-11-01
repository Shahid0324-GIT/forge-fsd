// Synthetic service: verifies capture substitution and actual process restart checks.
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {existsSync,readFileSync,writeFileSync} from 'node:fs';
function serve(){
  let row=process.argv[2]==='correct'&&existsSync('/tmp/calibration-data.json')?JSON.parse(readFileSync('/tmp/calibration-data.json','utf8')):null;
  return createServer(async(req,res)=>{
    if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end('<h1>Expenses</h1>');return;}
    res.setHeader('Content-Type','application/json');
    if(req.url==='/api/health'){res.end('{}');return;}
    if(req.method==='POST'&&['/api/expenses','/api/expenses/adjust'].includes(req.url)){
      let text='';for await(const chunk of req)text+=chunk;
      let input;try{input=JSON.parse(text);}catch{res.statusCode=400;res.end('{}');return;}
      if(!input||typeof input!=='object'||Array.isArray(input)){res.statusCode=400;res.end('{}');return;}
      if(input.amount<0){res.statusCode=400;res.end('{}');return;}
      if(req.url==='/api/expenses/adjust'&&(!row||input.expenseId!==row.id)){
        res.statusCode=404;res.end('{}');return;
      }
      row={id:1,amount:input.amount};writeFileSync('/tmp/calibration-data.json',JSON.stringify(row));res.statusCode=201;res.end(JSON.stringify(row));return;
    }
    if(req.url==='/api/expenses/1'&&row){res.end(JSON.stringify(row));return;}
    res.statusCode=404;res.end('{}');
  });
}
let code=0;
for(const phase of ['functional','persistence']){
  const server=serve();await new Promise(resolve=>server.listen(3000,'127.0.0.1',resolve));
  const child=spawn(process.execPath,['/trusted/application.mjs',phase],{stdio:'inherit'});
  code=await new Promise(resolve=>child.once('close',resolve));
  await new Promise(resolve=>server.close(resolve));
  if(code!==0)break;
}
process.exitCode=code;
