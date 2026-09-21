// Same-origin localhost:3000 entry point; desktop continues using its owned 4700
// Python process. No remote upstream, Host header, or executable is caller chosen.
import http from 'node:http';
const port=3000,upstreamPort=4700;
const server=http.createServer((req,res)=>{
 const hosts=new Set(['localhost:'+port,'127.0.0.1:'+port]);
 if(!hosts.has(req.headers.host)||(['cross-site','same-site'].includes(req.headers['sec-fetch-site'])&&!(req.method==='GET'&&req.headers['sec-fetch-mode']==='navigate'))||(req.headers.origin&&req.headers.origin!=='http://'+req.headers.host)){res.writeHead(403);res.end('Local requests only');return;}
 const headers={...req.headers,host:'127.0.0.1:'+upstreamPort};
 if(headers.origin)headers.origin='http://127.0.0.1:'+upstreamPort;
 delete headers['sec-fetch-site'];
 const proxy=http.request({hostname:'127.0.0.1',port:upstreamPort,path:req.url,method:req.method,headers},up=>{res.writeHead(up.statusCode,up.headers);up.pipe(res)});
 proxy.on('error',()=>{if(!res.headersSent)res.writeHead(503,{'Content-Type':'text/plain; charset=utf-8'});res.end('שרת ג׳רוויס אינו פועל. יש להפעיל את אפליקציית הדסקטופ.');});
 req.pipe(proxy);res.on('close',()=>proxy.destroy());
});
server.listen(port,'127.0.0.1',()=>console.log('JARVIS http://localhost:3000'));
