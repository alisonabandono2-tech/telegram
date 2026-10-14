import {NextRequest} from 'next/server';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
const allowed = /^(auth\/(status|phone|code|password)|leads(?:\/import|\/[0-9]+\/(send|block|delete))?)$/;
async function proxy(request:NextRequest, context:{params:Promise<{path:string[]}>}){
 const host=request.headers.get('host')||'';
 if(!/^(localhost|127\.0\.0\.1):3000$/.test(host))return Response.json({detail:'Acesso permitido somente pelo aplicativo local.'},{status:403});
 const origin=request.headers.get('origin');
 if((origin && origin!==`http://${host}`)||(request.method==='POST'&&!origin)||request.headers.get('sec-fetch-site')==='cross-site')return Response.json({detail:'Origem não autorizada.'},{status:403});
 const {path}=await context.params;const target=path.join('/');
 if(!allowed.test(target))return Response.json({detail:'Rota inexistente.'},{status:404});
 const token=process.env.APP_TOKEN;
 if(!token)return Response.json({detail:'Configuração local pendente: execute configurar-local.ps1 e reinicie o dashboard.'},{status:503});
 const declared=Number(request.headers.get('content-length')||'0');
 if(declared>11*1024*1024)return Response.json({detail:'Arquivo acima do limite.'},{status:413});
 try{
  const headers:Record<string,string>={Authorization:`Bearer ${token}`};
  const content=request.headers.get('content-type');if(content)headers['Content-Type']=content;
  const body=request.method==='POST'?await request.arrayBuffer():undefined;
  if(body&&body.byteLength>11*1024*1024)return Response.json({detail:'Arquivo acima do limite.'},{status:413});
  const response=await fetch(`http://127.0.0.1:8000/${target}`,{method:request.method,headers,body,cache:'no-store',signal:AbortSignal.timeout(120000)});
  const output=new Headers({'Content-Type':response.headers.get('Content-Type')||'application/json','Cache-Control':'no-store'});
  if(response.headers.has('Retry-After'))output.set('Retry-After',response.headers.get('Retry-After')!);
  return new Response(response.body,{status:response.status,headers:output});
 }catch{return Response.json({detail:'Backend indisponível ou resposta não confirmada. Se tentou enviar, confira a conversa antes de repetir.'},{status:502});}
}
export const GET=proxy;
export const POST=proxy;
