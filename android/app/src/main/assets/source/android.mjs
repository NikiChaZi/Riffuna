import { Innertube, Player, Constants, Platform, Log } from './youtubei.js';
import { createTokenProvider, PLAYBACK_USER_AGENT } from './attestation-core.mjs';
Log.setLevel(0);
Constants.URLS.API.PRODUCTION_1=Constants.URLS.API.PRODUCTION_2;
Platform.shim.eval=async(data)=>new Function(data.output)();
const trace=()=>{};
let httpSequence=0;
const httpRequests=new Map();
globalThis.riffunaHttpResponse=(id,response)=>httpRequests.get(id)?.(response);
function nativeRequest(payload,signal){
 return new Promise((resolve,reject)=>{
  if(signal?.aborted){reject(new DOMException('Request cancelled','AbortError'));return;}
  const id=++httpSequence;
  const finish=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);httpRequests.delete(id);};
  const abort=()=>{finish();Native.cancelHttp(id);reject(new DOMException('Request cancelled','AbortError'));};
  const timer=setTimeout(abort,30000);
  httpRequests.set(id,response=>{finish();resolve(response);});
  signal?.addEventListener('abort',abort,{once:true});
  try{Native.http(id,JSON.stringify(payload));}catch(error){finish();reject(error);}
 });
}
const nativeFetch=async(input,init={})=>{
 const request=new Request(input,init);
 const url=new URL(request.url);
 if(url.hostname==='youtubei.googleapis.com'&&!url.searchParams.has('key'))url.searchParams.set('key',Constants.CLIENTS.WEB.API_KEY);
 // Browser Request strips transport headers; preserve explicit provider headers for native HTTPS.
 const headers={...Object.fromEntries(request.headers.entries()),...Object.fromEntries(new Headers(init.headers||{}).entries())};
 if(!Object.keys(headers).some(key=>key.toLowerCase()==='user-agent'))headers['User-Agent']=PLAYBACK_USER_AGENT;
 const body=request.method==='GET'||request.method==='HEAD'?'':await request.text();
 const raw=JSON.parse(await nativeRequest({url:url.href,method:request.method,headers,body},request.signal));
 if(raw.error)throw Error('NetworkUnavailable');
 const bytes=Uint8Array.from(atob(raw.body||''),c=>c.charCodeAt(0));
 return new Response(request.method==='HEAD'||[204,205,304].includes(raw.status)?null:bytes,{status:raw.status,headers:raw.headers});
};
const boundedFetch=nativeFetch;
const mintPlaybackToken=createTokenProvider(nativeFetch,undefined,stage=>Native.issue("attestation",stage));
Platform.shim.fetch=nativeFetch;
let session;
const yt=async()=>session??=Innertube.create({lang:'en',location:'US',fetch:nativeFetch,retrieve_player:false,generate_session_locally:true,retrieve_innertube_config:false});
const playerRequests=new WeakMap();
async function ensurePlayer(api){
 if(api.session.player)return api.session.player;
 let pending=playerRequests.get(api);
 if(!pending){pending=Player.create(undefined,nativeFetch).then(player=>api.session.player=player).finally(()=>playerRequests.delete(api));playerRequests.set(api,pending);}
 return pending;
}
const searches=new Map();const metadata=new Map();const catalogIds=new Set();
const randomUUID=()=>globalThis.crypto.randomUUID?.()??Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)),value=>value.toString(16).padStart(2,'0')).join('');
function catalogName(value) {
 return String(value?.text ?? value ?? '').trim();
}

function catalogThumbnail(node) {
 const values = node?.thumbnails ?? node?.thumbnail?.contents ?? node?.thumbnail ?? node?.contents;
 return Array.isArray(values) ? thumb(values) : '';
}

function catalogEntry(row, kind, shelf = '') {
 if (row.item_type !== kind && row.type !== 'MusicCardShelf') return null;
 const id = row.id || row.endpoint?.payload?.browseId || row.on_tap?.payload?.browseId || '';
 const title = catalogName(row.name || row.title);
 const valid = kind === 'artist' ? /^UC[\w-]{22}$/.test(id) : /^MPR[\w-]{1,90}$/.test(id);
 if (!valid || !title) return null;
 const artist = row.author?.name || row.artists?.map(item => item.name).filter(Boolean).join(', ') || '';
 const subtitle = row.subtitle || row.flex_columns?.[1]?.title;
 const hint = catalogName(subtitle?.runs?.[0]?.text);
 const type = /\b(?:single|singles|ep)\b/i.test(hint + ' ' + shelf) ? 'single' : 'album';
 return { id, title, artist, type, year: catalogName(row.year), thumbnail: catalogThumbnail(row) };
}

function catalogTrackCredits(row) {
 const credits = [...(row.artists ?? []), ...(row.authors ?? [])];
 return distinctCatalogRows(credits.map(artist => {
  const id = artist.channel_id || artist.endpoint?.payload?.browseId || '';
  const title = catalogName(artist.name);
  return /^UC[\w-]{22}$/.test(id) && title ? { id, title } : null;
 }));
}

const catalogCredits = new Map();

function rememberCatalogCredits(id, row) {
 const credits = catalogTrackCredits(row);
 if (credits.length) {
  catalogCredits.set(id, credits);
  if (catalogCredits.size > 2000) catalogCredits.delete(catalogCredits.keys().next().value);
 }
 return credits;
}

async function catalogArtistsForTrack(id) {
 if (!/^[\w-]{11}$/.test(id)) throw Error('InvalidId');
 const cached = catalogCredits.get(id);
 if (cached) return { entries: cached };
 try {
  const queue = await (await yt()).music.getUpNext(id, false);
  const recording = queue.contents.find(row => row.video_id === id);
  if (recording) return { entries: rememberCatalogCredits(id, recording) };
 } catch {
  // An upload can have no YouTube Music credits. Let the client match its displayed names.
 }
 return { entries: [] };
}

function distinctCatalogRows(rows) {
 return [...new Map(rows.filter(Boolean).map(row => [row.id, row])).values()];
}

async function catalogSearch(query, kind) {
 if (!query || query.length > 500 || !['artist', 'album'].includes(kind)) throw Error('InvalidQuery');
 const page = await (await yt()).music.search(query, { type: kind });
 const rows = page.contents.flatMap(section =>
  section.type === 'MusicCardShelf' ? [section, ...(section.contents || [])] : section.contents || []
 );
 return { entries: distinctCatalogRows(rows.map(row => catalogEntry(row, kind))).slice(0, 40) };
}

function catalogTrack(row, artist, artwork, album = false) {
 // YouTube Music can point a numbered album track to the artist's official video.
 // Accept that source only in the release itself, never as a generic search result.
 const payload = row.flex_columns?.[0]?.title?.runs?.[0]?.endpoint?.payload;
 const videoType = payload?.watchEndpointMusicSupportedConfigs?.watchEndpointMusicConfig?.musicVideoType;
 const albumAudio = album && row.item_type === 'video' && /^\d+$/.test(catalogName(row.index))
  && payload?.videoId === row.id && videoType === 'MUSIC_VIDEO_TYPE_OMV';
 if (row.item_type !== 'song' && !albumAudio) return null;
 const track = musicRow(row);
 if (!track || !/^[\w-]{11}$/.test(track.id)) return null;
 rememberCatalogCredits(track.id, row);
 return {
  ...track,
  musicType: albumAudio ? 'MUSIC_VIDEO_TYPE_OMV' : track.musicType,
  artist: track.artist === 'YouTube' ? artist || track.artist : track.artist,
  thumbnail: track.thumbnail || artwork,
 };
}

const artistPages = new Map();
const artistContinuations = new Map();

async function getCatalogArtist(id) {
 if (!/^UC[\w-]{22}$/.test(id)) throw Error('InvalidId');
 const cached = artistPages.get(id);
 if (cached?.expires > Date.now()) return cached.page;
 const page = await (await yt()).music.getArtist(id);
 artistPages.set(id, { page, expires: Date.now() + 300_000 });
 if (artistPages.size > 24) artistPages.delete(artistPages.keys().next().value);
 return page;
}

function artistSongsShelf(page) {
 return page.sections.find(section => section.type === 'MusicShelf'
  && /^(top songs|songs)$/i.test(catalogName(section.title)));
}

async function catalogArtistTracks(id, cursor) {
 let page;
 let title;
 let thumbnail;
 if (cursor) {
  const saved = artistContinuations.get(cursor);
  if (!saved || saved.id !== id || saved.expires < Date.now()) return { expired: true };
  ({ title, thumbnail } = saved);
  try {
   page = await saved.page.getContinuation();
  } catch {
   return { retry: true };
  }
  artistContinuations.delete(cursor);
 } else {
  const artist = await getCatalogArtist(id);
  const shelf = artistSongsShelf(artist);
  title = catalogName(artist.header?.title);
  thumbnail = catalogThumbnail(artist.header) || thumb(artist.header?.foreground_thumbnail);
  const playlist = shelf?.endpoint?.payload?.browseId || '';
  if (!/^VL[\w-]{1,120}$/.test(playlist)) {
   return {
    tracks: distinctCatalogRows((shelf?.contents ?? []).map(row => catalogTrack(row, title, thumbnail))),
    partial: true,
   };
  }
  page = await (await yt()).music.getPlaylist(playlist);
 }
 const tracks = distinctCatalogRows((page.contents ?? []).map(row => catalogTrack(row, title, thumbnail)));
 let next = '';
 if (page.has_continuation) {
  next = randomUUID();
  artistContinuations.set(next, { id, page, title, thumbnail, expires: Date.now() + 1_800_000 });
  if (artistContinuations.size > 32) artistContinuations.delete(artistContinuations.keys().next().value);
 }
 return { tracks, cursor: next };
}

async function catalogArtist(id) {
 const page = await getCatalogArtist(id);
 const title = catalogName(page.header?.title);
 const thumbnail = catalogThumbnail(page.header) || thumb(page.header?.foreground_thumbnail);
 // The artist endpoint publishes popular tracks in MusicShelf, and releases in carousel shelves.
 const tracks = (artistSongsShelf(page)?.contents ?? []).map(row => catalogTrack(row, title, thumbnail));
 const releases = page.sections
  .filter(section => section.type === 'MusicCarouselShelf')
  .filter(section => /^(albums|singles(?:\s*(?:&|and)\s*eps)?|eps|releases)$/i.test(catalogName(section.header?.title)))
  .flatMap(section => (section.contents || []).map(row => catalogEntry(row, 'album', catalogName(section.header?.title))));
 return {
  title,
  thumbnail,
  tracks: distinctCatalogRows(tracks).slice(0, 5),
  releases: distinctCatalogRows(releases).slice(0, 80),
 };
}

async function catalogAlbum(id) {
 if (!/^MPR[\w-]{1,90}$/.test(id)) throw Error('InvalidId');
 const page = await (await yt()).music.getAlbum(id);
 const title = catalogName(page.header?.title);
 const thumbnail = catalogThumbnail(page.header);
 const authorRun = page.header?.strapline_text_one?.runs?.find(run =>
  /^UC[\w-]{22}$/.test(run.endpoint?.payload?.browseId || '')
 );
 const author = page.header?.author ?? (authorRun && {
  name: authorRun.text,
  channel_id: authorRun.endpoint.payload.browseId,
 });
 const artist = catalogName(author?.name);
 return {
  title,
  thumbnail,
  artist: artist && /^UC[\w-]{22}$/.test(author?.channel_id || '')
   ? { id: author.channel_id, title: artist, thumbnail: catalogThumbnail(page.header?.strapline_thumbnail) }
   : null,
  tracks: distinctCatalogRows(page.contents.map(row => catalogTrack(row, artist, thumbnail, true))),
 };
}


function thumb(values){
 const area=value=>(Number(value.width)||0)*(Number(value.height)||Number(value.width)||0);
 return [...(values||[])].filter(value=>value?.url).sort((a,b)=>area(b)-area(a))[0]?.url||'';
}
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

async function execute(r){
 if(r.action==='search'){const result=await musicSearch(String(r.query||''),Math.min(180,Math.max(1,r.limit||40)));setTimeout(()=>Promise.all([yt().then(ensurePlayer),mintPlaybackToken.prepare()]).catch(()=>{}),0);return result;}
 if(r.action==='catalog_search')return catalogSearch(String(r.query||''),r.kind);
 if(r.action==='catalog_artist')return catalogArtist(String(r.id||''));
 if(r.action==='catalog_artist_tracks')return catalogArtistTracks(String(r.id||''),String(r.cursor||''));
 if(r.action==='catalog_track_artists')return catalogArtistsForTrack(String(r.id||''));
 if(r.action==='catalog_album')return catalogAlbum(String(r.id||''));
 if(r.action==='resolve')return resolve(r.id,'webm');
 if(r.action==='metadata')return info(r.id);
 if(r.action==='videos')return videoSearch(String(r.query||''));
 if(r.action==='metadata_batch'){
  const ids=[...new Set(r.ids||[])].slice(0,80),tracks=[];
  for(let start=0;start<ids.length;start+=4)tracks.push(...await Promise.all(ids.slice(start,start+4).map(id=>info(id).catch(()=>null))));
  return {tracks:tracks.filter(Boolean)};
 }
 throw Error('UnknownAction');
}
globalThis.riffunaRequest=async(id,request)=>{
 try{Native.complete(id,JSON.stringify({ok:true,data:await execute(request)}));}
 catch(error){Native.issue(request.action,String(error.name||"Error"));session=undefined;Native.complete(id,JSON.stringify({ok:false,error:error.message==='StreamUnavailable'?'StreamUnavailable':'SourceUnavailable'}));}
};
Native.ready();
