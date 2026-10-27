import { Innertube, Player, Constants, Platform, Log } from './youtubei.js';
import { createTokenProvider, PLAYBACK_USER_AGENT } from './attestation-core.mjs';
Log.setLevel(0);
Constants.URLS.API.PRODUCTION_1=Constants.URLS.API.PRODUCTION_2;
Platform.shim.eval=async(data)=>new Function(data.output)();
const trace=()=>{};
const nativeFetch=async(input,init={})=>{
 const request=new Request(input,init);
 const url=new URL(request.url);
 if(url.hostname==='youtubei.googleapis.com'&&!url.searchParams.has('key'))url.searchParams.set('key',Constants.CLIENTS.WEB.API_KEY);
 // Browser Request strips transport headers; preserve explicit provider headers for native HTTPS.
 const headers={...Object.fromEntries(request.headers.entries()),...Object.fromEntries(new Headers(init.headers||{}).entries())};
 if(!Object.keys(headers).some(key=>key.toLowerCase()==='user-agent'))headers['User-Agent']=PLAYBACK_USER_AGENT;
 const body=request.method==='GET'||request.method==='HEAD'?'':await request.text();
 const raw=JSON.parse(Native.http(JSON.stringify({url:url.href,method:request.method,headers,body})));
 if(raw.error)throw Error('NetworkUnavailable');
 const bytes=Uint8Array.from(atob(raw.body||''),c=>c.charCodeAt(0));
 return new Response(request.method==='HEAD'||[204,205,304].includes(raw.status)?null:bytes,{status:raw.status,headers:raw.headers});
};
const boundedFetch=nativeFetch;
const mintPlaybackToken=createTokenProvider(nativeFetch,undefined,stage=>Native.issue("attestation",stage));
Platform.shim.fetch=nativeFetch;
let session;
const yt=async()=>session??=Innertube.create({lang:'en',location:'US',fetch:nativeFetch,retrieve_player:false,generate_session_locally:true,retrieve_innertube_config:false});
async function ensurePlayer(api){
 if(!api.session.player)api.session.player=await Player.create(undefined,nativeFetch);
 return api.session.player;
}
function thumb(values){return [...(values||[])].sort((a,b)=>Math.abs((a.width||120)-360)-Math.abs((b.width||120)-360))[0]?.url||'';}
const searches=new Map();
function musicRow(row){
 if(row.item_type!=='song'||!row.id||!row.title)return null;
 return {id:row.id,title:String(row.title),artist:(row.artists||row.authors||[]).map(a=>a.name).filter(Boolean).join(', ')||'YouTube',duration:row.duration?.seconds||0,thumbnail:thumb(row.thumbnail?.contents),musicType:'MUSIC_VIDEO_TYPE_ATV'};
}
/* RIFFUNA_MUSIC_SEARCH */
/* RIFFUNA_RESOLVE */

async function execute(r){
 if(r.action==='search'){const result=await musicSearch(String(r.query||''),Math.min(180,Math.max(1,r.limit||40)));setTimeout(()=>Promise.all([yt().then(ensurePlayer),mintPlaybackToken.prepare()]).catch(()=>{}),0);return result;}
 if(r.action==='resolve')return resolve(r.id);
 throw Error('UnknownAction');
}
globalThis.riffunaRequest=async(id,request)=>{
 try{Native.complete(id,JSON.stringify({ok:true,data:await execute(request)}));}
 catch(error){Native.issue(request.action,String(error.name||"Error"));session=undefined;Native.complete(id,JSON.stringify({ok:false,error:error.message==='StreamUnavailable'?'StreamUnavailable':'SourceUnavailable'}));}
};
Native.ready();
