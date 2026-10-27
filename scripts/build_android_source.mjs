import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const sha=data=>createHash('sha256').update(data).digest('hex');
const source=read('source-runtime/index.mjs');
const template=read('android/source-runtime/bridge.mjs');
const packageRoot=path.join(root,'source-runtime/node_modules/youtubei.js');
if(JSON.parse(fs.readFileSync(path.join(packageRoot,'package.json'),'utf8')).version!=='18.3.0')throw Error('Unexpected YouTube.js version');
function section(start,end){const first=source.indexOf(start);const last=source.indexOf(end,first+start.length);if(first<0||last<first)throw Error('Desktop source marker changed');return source.slice(first,last);}
const adapter=template.replace('/* RIFFUNA_MUSIC_SEARCH */\n',section('async function musicSearch(query,limit)','async function info(id)')).replace('/* RIFFUNA_RESOLVE */\n',section('async function resolve(','async function execute(request)'));
const outputs={
 'android.mjs':Buffer.from(adapter),
 'youtubei.js':fs.readFileSync(path.join(packageRoot,'bundle/browser.js')),
 'YOUTUBEJS-LICENSE.txt':fs.readFileSync(path.join(packageRoot,'LICENSE')),
 'index.html':Buffer.from(read('android/app/src/main/assets/source/index.html')),
};
const core=read('source-runtime/attestation-core.mjs').replaceAll("'bgutils-js/botguard'","'./bgutils/exports/botguard.js'").replaceAll("'bgutils-js/webpo'","'./bgutils/exports/webpo.js'").replaceAll("'bgutils-js/utils'","'./bgutils/exports/utils.js'");
outputs['attestation-core.mjs']=Buffer.from(core);
const bgRoot=path.join(root,'source-runtime/node_modules/bgutils-js');
if(JSON.parse(fs.readFileSync(path.join(bgRoot,'package.json'),'utf8')).version!=='4.0.3')throw Error('Unexpected attestation library version');
for(const entry of fs.readdirSync(path.join(bgRoot,'dist'),{recursive:true,withFileTypes:true})){
 if(entry.isFile()&&entry.name.endsWith('.js')){
  const absolute=path.join(entry.parentPath,entry.name);
  outputs['bgutils/'+path.relative(path.join(bgRoot,'dist'),absolute).split(path.sep).join('/')]=fs.readFileSync(absolute);
 }
}
outputs['BGUTILS-LICENSE.txt']=fs.readFileSync(path.join(bgRoot,'LICENSE'));
const manifest={youtubejs_version:'18.3.0',upstream:'https://github.com/LuanRT/YouTube.js',desktop_reference:'source-runtime/index.mjs',desktop_sha256:sha(source),template_sha256:sha(template),files:Object.fromEntries(Object.entries(outputs).sort(([a],[b])=>(a>b)-(a<b)).map(([name,data])=>[name,sha(data)]))};
outputs['BUILD-MANIFEST.json']=Buffer.from(JSON.stringify(manifest,null,2)+'\n');
const directory=path.join(root,'android/app/src/main/assets/source');
for(const [name,data] of Object.entries(outputs)){
 if(process.argv.includes('--restore-vendor')&&name!=='youtubei.js'&&!name.startsWith('bgutils/'))continue;
 const target=path.join(directory,name);
 if(process.argv.includes('--check')){if(!fs.existsSync(target)||!fs.readFileSync(target).equals(data))throw Error('Regenerate Android source: '+name);}
 else {fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,data);}
}
console.log(process.argv.includes('--check')?'Android source verified':process.argv.includes('--restore-vendor')?'Pinned Android vendor files restored':'Android source generated');
