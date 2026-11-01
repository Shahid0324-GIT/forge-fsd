// Synthetic HTTP service for checking the trusted acceptance harness, not a generated app.
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
const server=createServer(async(req,res)=>{
  if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end('<h1>Tip calculator</h1>');return;}
  res.setHeader('Content-Type','application/json');
  if(req.url==='/api/health'){res.end('{}');return;}
  if(req.url==='/api/calculate'){
    let text='';for await(const chunk of req)text+=chunk;
    let body;try{body=JSON.parse(text);}catch{res.statusCode=400;res.end('{}');return;}
    if(!body||typeof body!=='object'||Array.isArray(body)){res.statusCode=400;res.end('{}');return;}
    if(body.bill<0){res.statusCode=400;res.end('{"error":"invalid"}');return;}
    const tip=body.bill*body.tipPercent/100;
    res.end(JSON.stringify({tip,total:body.bill+tip,perPerson:process.argv[2]==='broken'?0:(body.bill+tip)/body.people}));return;
  }
  res.statusCode=404;res.end('{}');
});
await new Promise(resolve=>server.listen(3000,'127.0.0.1',resolve));
const child=spawn(process.execPath,['/trusted/application.mjs'],{stdio:'inherit'});
const code=await new Promise(resolve=>child.once('close',resolve));
await new Promise(resolve=>server.close(resolve));
process.exitCode=code;
