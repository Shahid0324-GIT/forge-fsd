// Trusted fixed-target HTTP proxy; no CONNECT, arbitrary destinations or source code.
import http from 'node:http';
const host=process.env.APP_HOST;
if(!/^forge-preview-[a-f0-9]{12}$/.test(host??'')) throw new Error('Invalid application identity');
const server=http.createServer((incoming,outgoing)=>{
  const headers={...incoming.headers};delete headers['proxy-authorization'];delete headers['proxy-connection'];
  const upstream=http.request({hostname:host,port:3000,path:incoming.url,method:incoming.method,headers},response=>{
    outgoing.writeHead(response.statusCode??502,response.headers);response.pipe(outgoing);
  });
  upstream.setTimeout(10000,()=>upstream.destroy(new Error('Upstream timeout')));
  upstream.on('error',()=>{if(!outgoing.headersSent)outgoing.writeHead(502);outgoing.end('Application is starting or unavailable');});
  incoming.pipe(upstream);incoming.on('aborted',()=>upstream.destroy());
});
server.on('connect',(_request,socket)=>socket.destroy());
server.listen(3000,'0.0.0.0');
setTimeout(()=>{server.close();process.exit(0);},30*60*1000);
