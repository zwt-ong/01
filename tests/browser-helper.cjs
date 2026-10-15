const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const helper=path.join(__dirname,'..','browser-helper');
function element(text='',selectors={},all={},attrs={}){return {innerText:text,textContent:text,querySelector:s=>selectors[s]||null,querySelectorAll:s=>all[s]||[],getClientRects:()=>[{}],getAttribute:s=>attrs[s]??null,...attrs};}
function readerTest(){
 const code=fs.readFileSync(path.join(helper,'page-reader.js'),'utf8');
 function read(hostname,pathname,selectors,all,body='normal page',title='fixture'){
  const context=vm.createContext({URL,document:{body:{innerText:body},title,querySelector:s=>selectors[s]||null,querySelectorAll:s=>all[s]||[]},location:{hostname,pathname,href:'https://'+hostname+pathname}});
  vm.runInContext(code,context);return JSON.parse(JSON.stringify(vm.runInContext('readRadarPage()',context)));
 }
 const dyAuthor=element('TEST 作者',{'[data-click-from="title"]':element('TEST 作者')},{},{href:'https://www.douyin.com/user/TESTauthor'});
 const result=read('www.douyin.com','/video/7695774571525410074',{'h1':element('TEST AI 编程方法'),'[data-e2e="detail-video-publish-time"]':element('发布时间：2026-10-12 21:35')},{'a[href*="/user/"]':[dyAuthor]},'章节要点 内容由AI生成 不应进入原文');
 assert.equal(result.items.length,1);assert.equal(result.items[0].published,'2026-10-12T21:35:00+08:00');
 assert.equal(result.items[0].creator,'TEST 作者');assert.equal(result.items[0].excerpt,undefined);
 assert.equal(result.items[0].body,undefined);
 assert.equal(read('www.douyin.com','/search/test',{}, {},'手机刷脸验证').blocked,true);
 assert.equal(read('www.douyin.com','/search/test',{}, {},'登录后即可搜索更多精彩视频').blocked,true);
 const card=element('',{'h3':element('TEST 我用AI做产品'),'a[href*="/video/BV"]':element('',{},{},{href:'https://www.bilibili.com/video/BV1Cupy6sEa9/'}),'.bili-video-card__info--author':element('TEST 作者'),'.bili-video-card__info--owner':element('',{},{},{href:'https://space.bilibili.com/123'}),'.bili-video-card__info--date':element('昨天'),'.bili-video-card__stats__duration':element('01:10')});
 const search=read('search.bilibili.com','/all',{}, {'.bili-video-card':[card,card]});
 assert.equal(search.items.length,1);assert.equal(search.items[0].duration_seconds,70);assert.equal(search.items[0].published,undefined);
 const biliDetail=read('www.bilibili.com','/video/BV1ezJC6PEoN/',{'h1':element('TEST 水墨游戏'),'.up-name':element('TEST 本人',{},{},{href:'https://space.bilibili.com/123'}),'.pubdate-ip-text':element('2026-10-15 11:49:39')},{'span':[],'span,time':[]});
 assert.equal(biliDetail.items[0].published,'2026-10-15T11:49:39+08:00');
 const standalone=vm.createContext({document:{body:null},location:{hostname:'www.douyin.com'}});
 vm.runInContext(code,standalone);
 // Serialize into a fresh isolated document with no previous global function injection.
 const readFunction=vm.runInContext('readRadarPage',standalone);
 const fresh={document:{body:null},location:{hostname:'www.douyin.com'}};
 assert.throws(()=>vm.runInNewContext('(()=>readRadarPage())()',fresh),/readRadarPage is not defined/);
 assert.equal(vm.runInNewContext('('+readFunction.toString()+')()',fresh).retryable,true);
 const notOwn=read('www.douyin.com','/user/TESTauthor',{'#semiTabpost':element('',{},{},{'aria-selected':'false'})},{'ul[data-e2e="scroll-list"] a[href*="/video/"]':[element('推荐视频')]});
 assert.equal(notOwn.items.length,0);
}
async function queueTest(){
 let memory={},requests=[],tabs=new Map(),nextId=1,blocked=false,duringRead=null,readReplies=[],nullRead=false;
 const b='https://www.bilibili.com/video/BV1Cupy6sEa9/',d='https://www.douyin.com/video/7695774571525410074';
 const jobs=[{url:'https://search.bilibili.com/all?keyword=vibe',platform:'B站',kind:'search'},{url:'https://www.douyin.com/search/vibe?type=video',platform:'抖音',kind:'search'}];
 const clone=v=>structuredClone(v);
 const chrome={storage:{local:{async get(keys){const k=typeof keys==='string'?[keys]:keys;return clone(Object.fromEntries(k.filter(x=>x in memory).map(x=>[x,memory[x]])));},async set(v){Object.assign(memory,clone(v));},async setAccessLevel(){} }},alarms:{async get(){return {};},async create(){},onAlarm:{addListener(){}}},action:{async setBadgeText(){}},runtime:{id:'a'.repeat(32),getURL:p=>'chrome-extension://'+'a'.repeat(32)+'/'+p,onStartup:{addListener(){}},onInstalled:{addListener(){}},onMessage:{addListener(){}}},tabs:{async create({url}){const tab={id:nextId++,url,status:'complete'};tabs.set(tab.id,tab);return tab;},async get(id){if(!tabs.has(id))throw new Error('closed');return tabs.get(id);},async remove(id){tabs.delete(id);},async update(id){return tabs.get(id);}},scripting:{async executeScript({target,files,func,args}){if(files||args)return [];assert.equal(func.name,'readRadarPage');if(readReplies.length)return readReplies.shift();if(nullRead)return [{frameId:0,result:null}];if(duringRead){const callback=duringRead;duringRead=null;await callback();}const tab=tabs.get(target.tabId);if(blocked)return [{result:{blocked:true,error:'需要本人验证',items:[]}}];const isB=tab.url.includes('bilibili');const url=isB?b:d;return [{result:{items:[{url,title:'TEST 我用AI做产品',creator:'TEST',creator_url:isB?'https://space.bilibili.com/999':'https://www.douyin.com/user/TESTauthor',platform:isB?'B站':'抖音',published:tab.url.includes('/video/')?'2026-10-14T12:00:00+08:00':''}]}}];}}};
 const fetch=async(url,options)=>{requests.push([url,options]);return {ok:true,json:async()=>url.endsWith('browser-jobs')?{jobs}:url.endsWith('browser-import')?{with_original_time:1}:{}};};
 const context=vm.createContext({chrome,URL,Date,AbortSignal,fetch,setTimeout:callback=>queueMicrotask(callback),console,module:{exports:{}},importScripts:file=>vm.runInContext(fs.readFileSync(path.join(helper,file),'utf8'),context)});
 vm.runInContext(fs.readFileSync(path.join(helper,'background.js'),'utf8'),context);
 const queue=context.module.exports;
 for(const frames of [null,undefined,[],[null],[{frameId:0,result:null}],[{result:undefined}],[{result:'bad'}],[{result:{items:null}}]]) {
   readReplies.push(frames);const result=await queue.readTab(1);assert.deepEqual(Array.from(result.items),[]);assert.equal(result.retryable,true);
 }
 nullRead=true;await queue.start();assert.equal(memory.run.phase,'paused');assert.equal(memory.run.queue.length,2);
 assert.doesNotMatch(memory.run.message,/Cannot read properties/);assert.equal(requests.filter(([url])=>url.endsWith('browser-import')).length,0);
 nullRead=false;await queue.command({action:'resume'});
 assert.equal(memory.run.phase,'running');assert.equal(memory.run.queue.length,1);
 await queue.command({action:'stop'});memory.run=null;requests=[];

 for(const bad of ['https://evil.test/video/123','https://www.douyin.com.evil.test/search/abc','http://www.douyin.com/search/abc','https://name:secret@www.douyin.com/search/abc','https://www.douyin.com:8443/search/abc'])assert.equal(queue.allowedUrl(bad),false);
 await queue.start();for(let i=0;i<4;i++)await queue.tick();
 assert.equal(memory.run.phase,'complete');assert.deepEqual(memory.run.counts,{'B站':1,'抖音':1});assert.equal(tabs.size,0);
 assert.equal(requests.filter(([url])=>url.endsWith('browser-import')).length,2);
 assert.equal(requests.filter(([url])=>url.endsWith('browser-finish')).length,1);
 memory.run=null;blocked=true;await queue.start();
 assert.equal(memory.run.phase,'paused');assert.equal(memory.run.queue.length,2);const pausedTab=memory.run.activeTab;
 assert.ok(tabs.has(pausedTab));blocked=false;await queue.command({action:'resume'});
 assert.equal(memory.run.phase,'running');assert.equal(memory.run.queue.length,1);assert.equal(tabs.has(pausedTab),false);
 await queue.command({action:'stop'});assert.equal(memory.run.phase,'stopped');assert.equal(memory.dailyEnabled,false);
 memory.run=null;blocked=true;await queue.start();await queue.command({action:'skip'});
 assert.equal(memory.run.phase,'running');assert.equal(memory.run.errors['B站'],true);assert.equal(memory.run.queue.length,1);
 await queue.command({action:'stop'});memory.run=null;blocked=false;
 const before=requests.filter(([url])=>url.endsWith('browser-import')).length;
 duringRead=()=>queue.command({action:'stop'});await queue.start();
 assert.equal(memory.run.phase,'stopped');
 assert.equal(requests.filter(([url])=>url.endsWith('browser-import')).length,before);
 memory.run=null;jobs.splice(0,jobs.length,{url:'https://space.bilibili.com/123',platform:'B站',kind:'creator'});
 await queue.start();await queue.tick();assert.equal(memory.run.phase,'paused');
 assert.match(memory.run.message,/上传者与追踪主页不一致/);
 assert.equal(requests.filter(([url])=>url.endsWith('browser-import')).length,before);
}
(async()=>{readerTest();await queueTest();console.log('Browser helper: DOM evidence, access boundaries, queue, pause/resume and stop passed');})().catch(e=>{console.error(e);process.exitCode=1;});
