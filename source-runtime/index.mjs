import { Innertube, UniversalCache, Player, Constants, Platform, Log } from 'youtubei.js';
import vm from 'node:vm';
import {createPlaybackTokenProvider} from './attestation.mjs';
import {PLAYBACK_USER_AGENT} from './attestation-core.mjs';
import readline from 'node:readline';
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import {randomUUID} from 'node:crypto';
import {Readable} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import { Agent, ProxyAgent, fetch as httpFetch, Request, Response, Headers } from 'undici';
Platform.shim.Request=Request;Platform.shim.Response=Response;Platform.shim.Headers=Headers;
Log.setLevel(0);
Constants.URLS.API.PRODUCTION_1=Constants.URLS.API.PRODUCTION_2;
Platform.shim.eval=async(data)=>vm.runInNewContext(`(function(){${data.output}\n})()`,{URL,URLSearchParams,TextEncoder,TextDecoder},{timeout:2500});
const trace=(value)=>{if(process.env.RIFFUNA_SOURCE_TRACE==='1')process.stderr.write(JSON.stringify({pid:process.pid,...value})+'\n');};
trace({phase:'start',proxy_configured:!!(process.env.HTTPS_PROXY||process.env.HTTP_PROXY)});
const fetchNative=httpFetch;
const proxyUri=process.env.HTTPS_PROXY||process.env.HTTP_PROXY;
const dispatcher=proxyUri?new ProxyAgent({uri:proxyUri,connections:4,connectTimeout:10000}):undefined;
const boundedFetch=async(input,init={})=>{
 const value=typeof input==='string'?input:input instanceof URL?input.href:input.url;const url=new URL(value);
 if(url.hostname==='youtubei.googleapis.com'&&!url.searchParams.has('key')){url.searchParams.set('key',Constants.CLIENTS.WEB.API_KEY);input=new Request(url,input instanceof Request?input:undefined);}
 const phase=url.pathname.includes('iframe_api')?'player-version':url.pathname.endsWith('base.js')?'player-script':url.pathname.includes('/player')?'player-api':url.hostname.endsWith('googlevideo.com')?'audio-range':'session-api';
 const headers=new Headers(init.headers||(input instanceof Request?input.headers:undefined));
 const selectedDispatcher=init.dispatcher||dispatcher;
 try{const response=await fetchNative(input,{...init,headers,...(selectedDispatcher?{dispatcher:selectedDispatcher}:{}),signal:AbortSignal.any([...(init.signal?[init.signal]:[]),AbortSignal.timeout(18000)])});trace({phase,status:response.status});return response;}
 catch(error){trace({phase,type:error.name,cause:error.cause?.code||'',proxy_endpoint:!!proxyUri&&String(error.cause?.message||'').includes(new URL(proxyUri).host),main_youtube:url.hostname==='www.youtube.com',music_youtube:url.hostname==='music.youtube.com'});throw error;}
};
const mintPlaybackToken=createPlaybackTokenProvider(boundedFetch);
let bridgeServer;let bridgeAddress;const bridgeToken='/'+randomUUID();const bridgeAgents=new Map();
function bridgeAgent(proxy){
 if(!bridgeAgents.has(proxy))bridgeAgents.set(proxy,proxy?new ProxyAgent({uri:proxy,connections:4,connectTimeout:10000}):new Agent({connections:4,connectTimeout:10000}));
 return bridgeAgents.get(proxy);
}
async function rangeBridge(){
 if(bridgeAddress)return bridgeAddress;
 bridgeServer=http.createServer(async(request,response)=>{
  if(request.method!=='POST'||request.url!==bridgeToken){response.writeHead(404);response.end();return;}
  const controller=new AbortController();response.once('close',()=>controller.abort());
  try{
   const chunks=[];let length=0;
   for await(const chunk of request){length+=chunk.length;if(length>65536)throw Error('RequestTooLarge');chunks.push(chunk);}
   const payload=JSON.parse(Buffer.concat(chunks).toString('utf8'));const target=new URL(payload.uri);
   if(target.protocol!=='https:'||!(target.hostname==='googlevideo.com'||target.hostname.endsWith('.googlevideo.com')))throw Error('InvalidHost');
   const match=/^bytes=(\d+)-(\d+)$/.exec(payload.range||'');if(!match)throw Error('InvalidRange');
   const start=Number(match[1]),end=Number(match[2]);if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||end<start||end-start>=8*1024*1024)throw Error('InvalidRange');
   const proxy=String(payload.proxy||'');if(proxy&&!['http:','https:'].includes(new URL(proxy).protocol))throw Error('InvalidProxy');
   const headers=new Headers(payload.headers||{});for(const name of ['host','connection','content-length','proxy-authorization','transfer-encoding'])headers.delete(name);
   headers.set('Range',payload.range);headers.set('Accept-Encoding','identity');
   const upstream=await boundedFetch(target,{headers,dispatcher:bridgeAgent(proxy),signal:controller.signal});
   const forwarded={};for(const name of ['content-type','content-length','content-range','accept-ranges']){const value=upstream.headers.get(name);if(value!==null)forwarded[name]=value;}
   response.writeHead(upstream.status,forwarded);trace({phase:'range-bridge',status:upstream.status});
   if(upstream.body)await pipeline(Readable.fromWeb(upstream.body),response);else response.end();
  }catch(error){trace({phase:'range-bridge-error',type:error.name});if(!response.headersSent){response.writeHead(502);response.end();}else response.destroy();}
  finally{controller.abort();}
 });
 await new Promise((resolve,reject)=>{bridgeServer.once('error',reject);bridgeServer.listen(0,'127.0.0.1',resolve);});
 bridgeAddress='http://127.0.0.1:'+bridgeServer.address().port+bridgeToken;return bridgeAddress;
}

let session;
const cacheDirectory=path.resolve(process.argv[2]);
const playerManifest=path.join(cacheDirectory,'riffuna-player.json');
async function createSession(){
 return Innertube.create({lang:'en',location:'US',cache:new UniversalCache(true,cacheDirectory),fetch:boundedFetch,retrieve_player:false,generate_session_locally:true,retrieve_innertube_config:false});
}
async function ensurePlayer(api){
 if(api.session.player)return api.session.player;
 let playerId;let verifiedAt=Date.now();
 try{const saved=JSON.parse(await fs.readFile(playerManifest,'utf8'));if(/^[a-f0-9]{8}$/i.test(saved.id)&&Date.now()-saved.at>=0&&Date.now()-saved.at<900000){playerId=saved.id;verifiedAt=saved.at;}}catch{}
 let player;
 try{player=await Player.create(api.session.cache,boundedFetch,undefined,playerId);}
 catch(error){if(!playerId)throw error;await fs.rm(playerManifest,{force:true}).catch(()=>{});verifiedAt=Date.now();player=await Player.create(api.session.cache,boundedFetch);}
 api.session.player=player;
 const temporary=playerManifest+'.'+process.pid+'.tmp';
 try{await fs.mkdir(cacheDirectory,{recursive:true});await fs.writeFile(temporary,JSON.stringify({id:player.player_id,at:verifiedAt}));await fs.rename(temporary,playerManifest);}catch{}finally{await fs.rm(temporary,{force:true}).catch(()=>{});}
 return player;
}
const yt=async()=>session??=createSession();
const searches=new Map();const metadata=new Map();const catalogIds=new Set();
function thumb(values){return [...(values||[])].sort((a,b)=>Math.abs((a.width||120)-360)-Math.abs((b.width||120)-360))[0]?.url||'';}
function musicRow(row){
 if(row.item_type==='song'&&row.id){catalogIds.add(row.id);while(catalogIds.size>2000)catalogIds.delete(catalogIds.values().next().value);}
 if(!row.id||!row.title)return null;
 return {id:row.id,title:String(row.title),artist:(row.artists||row.authors||[]).map(a=>a.name).filter(Boolean).join(', ')||'YouTube',duration:row.duration?.seconds||0,thumbnail:thumb(row.thumbnail?.contents),musicType:row.item_type==='song'?'MUSIC_VIDEO_TYPE_ATV':row.item_type==='video'?'MUSIC_VIDEO_TYPE_UGC':'',album:row.album?.name||'',live:false};
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
async function info(id){
 if(!/^[\w-]{11}$/.test(id))throw Error('InvalidId');
 const saved=metadata.get(id);if(saved?.expires>Date.now())return saved.row;
 const api=await yt();const value=await api.getBasicInfo(id,{client:'WEB'});const b=value.basic_info;
 const raw=value.page?.[0]?.video_details||{};
 let available=value.playability_status?.status==='OK';
 let live=!!(b.is_live||b.is_live_content||b.is_upcoming);
 let type=b.music_video_type||raw.music_video_type||'';
 if(!type&&catalogIds.has(id))type='MUSIC_VIDEO_TYPE_ATV';
 if(!type)try{const music=await api.session.actions.execute('/player',{videoId:id,client:'YTMUSIC'});type=music.data?.videoDetails?.musicVideoType||music.data?.currentVideoEndpoint?.watchEndpoint?.watchEndpointMusicSupportedConfigs?.watchEndpointMusicConfig?.musicVideoType||'';if(music.data?.videoDetails?.videoId===id&&music.data?.playabilityStatus?.status==='OK')available=true;}catch{}

 if(!available)for(const client of ['VISIONOS','IOS'])try{const playable=await api.getBasicInfo(id,{client});if(playable.basic_info.id===id&&playable.playability_status?.status==='OK'){available=true;live=live||!!(playable.basic_info.is_live||playable.basic_info.is_live_content||playable.basic_info.is_upcoming);break;}}catch{}
 const row={id:b.id||id,title:b.title||'',artist:(b.author||b.channel?.name||'YouTube').replace(/\s*[-–—]\s*Topic\s*$/i,''),duration:b.duration||b.length_seconds||0,thumbnail:thumb(b.thumbnail),musicType:type,category:b.category||'',live,viewCount:Number.isSafeInteger(b.view_count)?b.view_count:null,published:b.publish_date||'',storyboards:value.storyboards?.boards||[],available};
 metadata.set(id,{row,expires:Date.now()+300000});while(metadata.size>250)metadata.delete(metadata.keys().next().value);
 return row;
}
async function videoSearch(query){
 const page=await(await yt()).search(query,{type:'video'});
 return {tracks:(page.videos||[]).slice(0,16).map(v=>({id:v.id,title:v.title?.text||String(v.title||''),artist:v.author?.name||'YouTube',duration:v.duration?.seconds||0,thumbnail:thumb(v.thumbnails),live:!!v.is_live,musicType:''}))};
}
async function resolve(id,preferredContainer='mp4'){
 if(!/^[\w-]{11}$/.test(id))throw Error('InvalidId');
 const api=await yt();
 const preference=f=>((f.is_original||/original|оригинал/i.test(f.audio_track?.display_name||''))?1000000:0)-((f.is_dubbed||f.is_auto_dubbed||f.is_descriptive||f.is_secondary)?2000000:0)+(f.audio_track?.audio_is_default?500000:0)+(f.mime_type?.includes(preferredContainer==='webm'?'webm':'mp4')?100000:0)+(Math.min(Number(f.bitrate)||0,200000)/10);
 const formatsFor=value=>{
  const formats=(value.streaming_data?.adaptive_formats||[]).filter(f=>f.has_audio&&!f.has_video&&(f.url||f.signature_cipher||f.cipher)).sort((a,b)=>preference(b)-preference(a));
  const identity=f=>f.audio_track?.id||f.audio_track?.display_name||'';
  const matching=formats.filter(f=>identity(f)===identity(formats[0]||{}));
  const first=matching[0];
  const alternative=matching.find(f=>f.mime_type?.split(';')[0]!==first?.mime_type?.split(';')[0]);
  return [first,alternative||matching[1]].filter(Boolean);
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
   try{
    const url=new URL(await format.decipher(api.session.player));url.searchParams.set('pot',token);
    const stream=await validate(url.href,'YTMUSIC');if(stream)return stream;
   }catch(error){trace({phase:'attested-format-error',type:error.name});}
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
async function execute(request){
 switch(request.action){
 case 'range_bridge':return {uri:await rangeBridge()};
 case 'prepare_playback':{const api=await yt();await Promise.all([ensurePlayer(api),mintPlaybackToken.prepare()]);return {ready:true};}
 case 'capabilities':return {qt_loaded:false,python:false,protocol:2,provider:'youtubei.js',version:'18.3.0'};
 case 'search':return musicSearch(String(request.query||''),Math.min(180,Math.max(1,request.limit||80)));
 case 'videos':return videoSearch(String(request.query||''));
 case 'metadata':return info(request.id);
 case 'metadata_batch':{
  const ids=[...new Set(request.ids||[])].slice(0,80);const rows=[];
  for(let start=0;start<ids.length;start+=4)rows.push(...await Promise.all(ids.slice(start,start+4).map(id=>info(id).catch(()=>null))));
  return {tracks:rows.filter(Boolean)};
 }
 case 'resolve':return resolve(request.track.id);
 default:throw Error('InvalidAction');
 }
}
const lines=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
try{for await(const line of lines){
 if(Buffer.byteLength(line,'utf8')>65536)break;
 try{const request=JSON.parse(line);const result=await execute(request);process.stdout.write(JSON.stringify({ok:true,result})+'\n');}
 catch(error){session=undefined;if(error.message==='StreamUnavailable'||error.name==='PlayerError')await fs.rm(playerManifest,{force:true}).catch(()=>{});process.stdout.write(JSON.stringify({ok:false,error:error.message==='StreamUnavailable'?'StreamUnavailable':'SourceError',error_type:String(error.name||'Error').replace(/[^A-Za-z]/g,'').slice(0,50),cause_code:String(error.cause?.code||'').replace(/[^A-Z_]/g,'').slice(0,60)})+'\n');}
}
}finally{if(bridgeServer){bridgeServer.closeAllConnections();await new Promise(resolve=>bridgeServer.close(resolve));}await dispatcher?.destroy();for(const agent of bridgeAgents.values())await agent.destroy();}
