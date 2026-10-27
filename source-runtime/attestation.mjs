import {createTokenProvider} from './attestation-core.mjs';
import {USER_AGENT} from 'bgutils-js/utils';
let environment;
export function createPlaybackTokenProvider(fetchFunction){
 return createTokenProvider(fetchFunction,async()=>{
  if(!environment){
   const {JSDOM}=await import('jsdom');
   const dom=new JSDOM('<!DOCTYPE html><html><body></body></html>',{url:'https://www.youtube.com/',referrer:'https://www.youtube.com/',userAgent:USER_AGENT});
   Object.assign(globalThis,{window:dom.window,document:dom.window.document,location:dom.window.location,origin:dom.window.origin});
   Object.defineProperty(globalThis,'navigator',{value:dom.window.navigator,configurable:true});
   environment={globalObject:globalThis,evaluate:script=>new Function(script)()};
  }
  return environment;
 });
}
