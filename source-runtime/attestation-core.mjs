import {BotGuardClient,getChallenge} from 'bgutils-js/botguard';
import {WebPoMinter} from 'bgutils-js/webpo';
export {USER_AGENT as PLAYBACK_USER_AGENT} from 'bgutils-js/utils';
import {buildURL,getHeaders} from 'bgutils-js/utils';

// Anonymous, content-bound playback tokens. No account cookies or tokens are persisted.
export function createTokenProvider(fetchFunction,prepareEnvironment=async()=>({globalObject:globalThis,evaluate:script=>new Function(script)()}),report=()=>{}){
 let cached;let pending;
 async function create(){
  const environment=await prepareEnvironment();report("environment");
  const requestKey='O43z0dpjhgX20SCx4KAo';
  const challenge=await getChallenge({fetchFunction,requestKey});
  report("challenge");
  const script=challenge.interpreterJavascript?.privateDoNotAccessOrElseSafeScriptWrappedValue;
  if(!script)throw Error('PlaybackInterpreterUnavailable');
  environment.evaluate(script);report("interpreter");
  const client=await BotGuardClient.create({program:challenge.program,globalName:challenge.globalName,globalObject:environment.globalObject});
  report("client");
  const signals=[];const response=await client.snapshot({webPoSignalOutput:signals});report("snapshot");
  const result=await fetchFunction(buildURL('GenerateIT',true),{method:'POST',headers:getHeaders(),body:JSON.stringify([requestKey,response])});
  if(!result.ok)throw Error('PlaybackIntegrityUnavailable');
  const [integrityToken,estimatedTtlSecs,mintRefreshThreshold,websafeFallbackToken]=await result.json();
  if(!integrityToken||!Number.isFinite(estimatedTtlSecs)||estimatedTtlSecs<=60)throw Error('PlaybackIntegrityRejected');
  report("integrity");
  const minter=await WebPoMinter.create({integrityToken,estimatedTtlSecs,mintRefreshThreshold,websafeFallbackToken},signals);
  report("ready");
  return {minter,expires:Date.now()+Math.min(3600,estimatedTtlSecs-60)*1000};
 }
 async function prepare(){
  if(!cached||cached.expires<=Date.now()){
   pending??=create().then(value=>cached=value).finally(()=>pending=undefined);
   await pending;
  }
 }
 const mint=async id=>{
  if(!/^[\w-]{11}$/.test(id))throw Error('InvalidId');
  await prepare();
  return cached.minter.mintAsWebsafeString(id);
 };
 mint.prepare=prepare;
 return mint;
}
