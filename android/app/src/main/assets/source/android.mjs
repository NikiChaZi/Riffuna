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
async function musicSearch(query,limit){
 const old=searches.get(query);if(old&&old.expires>Date.now()&&(old.rows.length>=limit||old.done))return {tracks:old.rows.slice(0,limit)};
 const api=await yt();let page=old?.expires>Date.now()?old.page:await api.music.search(query,{type:'song'});
 const rows=old?.expires>Date.now()?[...old.rows]:[];const seen=new Set(rows.map(x=>x.id));let done=false;
 for(let count=0;count<8;count++){
  const items=Array.isArray(page.contents)?page.contents.flatMap(s=>s.contents||[]):page.contents?.contents||[];
  for(const item of items){const row=musicRow(item);if(row&&!seen.has(row.id)){seen.add(row.id);rows.push(row);}}
  if(rows.length>=limit)break;
  try{page=await page.getContinuation();}catch{done=true;break;}
 }
 searches.set(query,{rows,page,done,expires:Date.now()+300000});while(searches.size>12)searches.delete(searches.keys().next().value);
 return {tracks:rows.slice(0,limit)};
}
async function resolve(id){
 if(!/^[\w-]{11}$/.test(id))throw Error('InvalidId');
 const api=await yt();
 const preference=f=>((f.is_original||/original|оригинал/i.test(f.audio_track?.display_name||''))?1000000:0)-((f.is_dubbed||f.is_auto_dubbed||f.is_descriptive||f.is_secondary)?2000000:0)+(f.audio_track?.audio_is_default?500000:0)+(f.mime_type?.includes('mp4')?100000:0)+(Math.min(Number(f.bitrate)||0,200000)/10);
 const formatsFor=value=>{
  const formats=(value.streaming_data?.adaptive_formats||[]).filter(f=>f.has_audio&&!f.has_video&&(f.url||f.signature_cipher||f.cipher)).sort((a,b)=>preference(b)-preference(a));
  const identity=f=>f.audio_track?.id||f.audio_track?.display_name||'';
  return formats.filter(f=>identity(f)===identity(formats[0]||{})).slice(0,2);
 };
 const validate=async(url,client)=>{
  const parsed=new URL(url);if(parsed.protocol!=='https:'||!(parsed.hostname==='googlevideo.com'||parsed.hostname.endsWith('.googlevideo.com')))return null;
  const headers={'User-Agent':Constants.CLIENTS[client]?.USER_AGENT||PLAYBACK_USER_AGENT,'Accept':'*/*','Accept-Encoding':'identity'};
  const response=await boundedFetch(url,{headers:{...headers,Range:'bytes=0-1023'}});await response.body?.cancel();
  if(response.status!==206)return null;
  const size=Number(parsed.searchParams.get('clen'));
  // Tiny probes can succeed on a preview-capped link. Verify a real range at the end too.
  if(Number.isSafeInteger(size)&&size>131072){
   const tailStart=Math.max(0,size-131072);
   const tail=await boundedFetch(url,{headers:{...headers,Range:'bytes='+tailStart+'-'+(size-1)}});
   const valid=tail.status===206&&tail.headers.get('content-range')==='bytes '+tailStart+'-'+(size-1)+'/'+size;
   if(!valid){await tail.body?.cancel();return null;}
   if((await tail.arrayBuffer()).byteLength!==size-tailStart)return null;
  }
  trace({phase:'audio-ready',client});
  return {uri:url,headers,client};
 };
 // Web playback uses a content-bound attestation token; native-client preview links are insufficient.
 try{
  const [,token]=await Promise.all([ensurePlayer(api),mintPlaybackToken(id)]);
  const value=await api.getBasicInfo(id,{client:'YTMUSIC'});
  if(value.basic_info.id===id)for(const format of formatsFor(value)){
   const url=new URL(await format.decipher(api.session.player));url.searchParams.set('pot',token);
   const stream=await validate(url.href,'YTMUSIC');if(stream)return stream;
  }
 }catch(error){trace({phase:'attested-client-error',type:error.name});}
 for(const client of ['VISIONOS','IOS','ANDROID_VR']){
  try{
   const value=await api.getBasicInfo(id,{client});if(value.basic_info.id!==id)continue;
   const formats=formatsFor(value);trace({phase:'direct-client',client,formats:formats.length});
   for(const format of formats){if(!format.url||format.signature_cipher||format.cipher||new URL(format.url).searchParams.has('n'))continue;const stream=await validate(format.url,client);if(stream)return stream;}
  }catch(error){trace({phase:'direct-client-error',client,type:error.name});}
 }
 await ensurePlayer(api);
 for(const client of ['VISIONOS','WEB_EMBEDDED','IOS','ANDROID_VR','TV_SIMPLY','WEB']){
  try{
   const value=await api.getBasicInfo(id,{client});if(value.basic_info.id!==id)continue;
   for(const format of formatsFor(value)){const stream=await validate(await format.decipher(api.session.player),client);if(stream)return stream;}
  }catch(error){trace({phase:'signed-client-error',client,type:error.name});}
 }
 throw Error('StreamUnavailable');
}

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
