import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('./index.mjs',import.meta.url),'utf8');
const start=source.indexOf('function thumb(values)');
const end=source.indexOf('function musicRow(row)',start);
const thumb=vm.runInNewContext(source.slice(start,end)+';thumb');
test('choose actual largest cover regardless of provider order',()=>{
 const small={url:'small',width:120,height:120};
 const medium={url:'medium',width:360,height:360};
 const large={url:'large',width:1024,height:1024};
 assert.equal(thumb([large,small,medium]),'large');
 assert.equal(thumb([medium,large,small]),'large');
 assert.equal(thumb([{width:2048,height:2048},small]),'small');
 assert.equal(thumb([]),'');
 assert.equal(thumb(undefined),'');
});
