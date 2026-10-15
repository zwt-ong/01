/* Resumable queue, normal pages only. No requests to platform APIs. */
// Inject the complete function on each read; page navigation can replace the document.
importScripts('page-reader.js');
const BASE='http://127.0.0.1:8765';
let busy=false;
const day=()=>new Date(Date.now()+8*3600000).toISOString().slice(0,10);
function allowedUrl(value) {
  try {
    const u=new URL(value);
    return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&(
      u.hostname==='search.bilibili.com'&&u.pathname==='/all'||
      u.hostname==='space.bilibili.com'&&/^\/\d+(?:\/upload(?:\/video)?)?\/?$/.test(u.pathname)||
      u.hostname==='www.bilibili.com'&&/^\/video\/BV[A-Za-z0-9]{10}\/?$/.test(u.pathname)||
      u.hostname==='www.douyin.com'&&(/^\/search\/[^/]+$/.test(u.pathname)||/^\/user\/[A-Za-z0-9_-]+$/.test(u.pathname)||/^\/video\/\d{8,30}$/.test(u.pathname)));
  }catch{return false;}
}
async function api(path,value) {
  const {pairToken}=await chrome.storage.local.get('pairToken');
  const response=await fetch(BASE+path,{method:value===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-01-Browser-Token':pairToken||''},body:value===undefined?undefined:JSON.stringify(value),signal:AbortSignal.timeout(8000)});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'本地01连接失败');return data;
}
async function ensureAlarm() {if(!(await chrome.alarms.get('01-tick')))await chrome.alarms.create('01-tick',{periodInMinutes:1});}
async function start() {
  const {run:old}=await chrome.storage.local.get('run');
  if(busy||old&&['running','paused'].includes(old.phase))throw new Error('本轮尚未结束，请继续、跳过或停止');
  const data=await api('/api/browser-jobs');
  const tasks=data.jobs.filter(job=>allowedUrl(job.url));
  if(!tasks.length)throw new Error('01尚未配置搜索或作者');
  tasks.sort((a,b)=>(a.kind==='creator'?0:1)-(b.kind==='creator'?0:1));
  await chrome.storage.local.set({run:{queue:tasks,details:[],detailCount:{'B站':0,'抖音':0},seen:[],counts:{'B站':0,'抖音':0},errors:{},phase:'running',message:'开始读取正常网页',started:Date.now(),id:Date.now()+'-'+Math.random()},lastDay:day()});
  await ensureAlarm();await tick();
}
async function readTab(id) {
  try {
    const frames=await chrome.scripting.executeScript({target:{tabId:id},func:readRadarPage});
    const frame=Array.isArray(frames)?frames.find(frame=>frame?.frameId===0)||frames[0]:null;
    const result=frame?.result;
    if(!result||typeof result!=='object'||Array.isArray(result)||!Array.isArray(result.items))return {items:[],retryable:true,error:'网页切换或加载中，暂未返回作品资料'};
    return result;
  }catch(error) {
    if(/context|frame.*removed|document.*unloaded|navigat/i.test(error.message||''))return {items:[],retryable:true,error:'网页正在切换，请等待后继续'};
    throw error;
  }
}
async function page(job,run) {
  let tab;
  if(run.activeTab) {try {tab=await chrome.tabs.get(run.activeTab);}catch{delete run.activeTab;}}
  if(!tab) {
    tab=await chrome.tabs.create({url:job.url,active:false});
    run.activeTab=tab.id;await chrome.storage.local.set({run});
  }
  try {
    const deadline=Date.now()+15000;
    while(Date.now()<deadline) {
      if((await chrome.tabs.get(tab.id)).status==='complete')break;
      await new Promise(r=>setTimeout(r,500));
    }
    if(!allowedUrl((await chrome.tabs.get(tab.id)).url))throw new Error('页面跳转到支持范围以外，请本人检查');
    let result;
    for(let i=0;i<5;i++) {
      result=await readTab(tab.id);
      if(result.blocked)return {...result,tabId:tab.id};
      if(result.items?.length)break;
      await new Promise(r=>setTimeout(r,750));
    }
    if(job.kind!=='detail')await chrome.scripting.executeScript({target:{tabId:tab.id},func:prepareRadarPage,args:[job.kind]});
    for(let i=0;i<8;i++) {
      result=await readTab(tab.id);
      if(result.blocked)return {...result,tabId:tab.id};
      if(result.items.length&&(job.kind!=='detail'||result.items.some(item=>item.published)))break;
      await new Promise(r=>setTimeout(r,750));
    }
    if(result.items?.length) {await chrome.tabs.remove(tab.id);delete run.activeTab;return result;}
    return {...result,blocked:true,tabId:tab.id};
  }catch(error) {return {blocked:true,tabId:tab.id,error:error.message,items:[]};}
}
async function tick() {
  if(busy)return;busy=true;
  try {
    let {run,dailyEnabled,lastDay}=await chrome.storage.local.get(['run','dailyEnabled','lastDay']);
    if(!run||run.phase==='complete'||run.phase==='stopped') {
      if(dailyEnabled&&lastDay!==day()) {busy=false;await start();}
      return;
    }
    if(run.phase!=='running')return;
    const job=run.queue[0]||run.details[0];
    if(!job) {
      for(const platform of Object.keys(run.counts))await api('/api/browser-status',{platform,ok:!run.errors[platform],count:run.counts[platform],message:run.errors[platform]?'本轮有页面跳过，结果不完整':'浏览器读取完成；作品资料不是字幕'});
      await api('/api/browser-finish',{});
      run.phase='complete';run.message=`本轮结束：B站 ${run.counts['B站']} 条，抖音 ${run.counts['抖音']} 条带原始时间。${Object.keys(run.errors).length?'存在跳过页面。':''}请到01核对候选。`;
      await chrome.storage.local.set({run});return;
    }
    run.current={platform:job.platform,kind:job.kind,url:job.url};
    const result=await page(job,run);
    const {cancelledId}=await chrome.storage.local.get('cancelledId');
    if(cancelledId===run.id)return;
    if(!result||result.blocked) {
      run.phase='paused';run.message=`${job.platform}：${result?.error||'网页暂未返回有效资料，请稍后继续'}`;
      await chrome.storage.local.set({run});await chrome.action.setBadgeText({text:'!'});
      await api('/api/browser-status',{platform:job.platform,ok:false,count:run.counts[job.platform],message:run.message}).catch(()=>{});return;
    }
    if(job.kind==='detail') {
      // Never merge results from recommendations or a different video into this job.
      const match=result.items.find(item=>item.url.replace(/\/$/,'')===job.url.replace(/\/$/,''));
      if(!match)throw new Error('作品链接不一致，本轮暂停');
      if(job.author_url && (!match.creator_url || new URL(match.creator_url).pathname.replace(/\/$/,'')!==new URL(job.author_url).pathname.replace(/\/$/,'')))throw new Error('作品上传者与追踪主页不一致，请本人核对');
      const item={...job.item,...match,duration_seconds:match.duration_seconds??job.item.duration_seconds};
      const response=await api('/api/browser-import',{items:[item]});
      run.counts[job.platform]+=response.with_original_time;run.details.shift();
    } else {
      for(const item of result.items.slice(0,8)) {
        if(!allowedUrl(item.url)||run.seen.includes(item.url)||run.detailCount[job.platform]>=10)continue;
        run.seen.push(item.url);run.detailCount[job.platform]++;
        run.details.push({kind:'detail',url:item.url,platform:job.platform,item,author_url:job.kind==='creator'?job.url:''});
      }
      run.queue.shift();
    }
    const next=run.queue[0]||run.details[0];
    run.message=`已读取：${job.platform}；下一页：${next?.platform||'整理日报'}；剩余页面 ${run.queue.length+run.details.length}`;
    await chrome.storage.local.set({run});await chrome.action.setBadgeText({text:''});
  } catch(error) {
    const {run,cancelledId}=await chrome.storage.local.get(['run','cancelledId']);
    if(run&&run.id!==cancelledId){run.phase='paused';run.message=error.message;await chrome.storage.local.set({run});}
  } finally {busy=false;}
}
async function command(message) {
  if(message.action==='pair') {
    if(!/^[A-Za-z0-9_-]{40,60}$/.test(message.token||''))throw new Error('配对码格式无效');
    await chrome.storage.local.set({pairToken:message.token});await api('/api/browser-jobs');
  }
  if(message.action==='run')await start();
  if(message.action==='resume') {const {run}=await chrome.storage.local.get('run');if(run?.phase==='paused'){run.phase='running';await chrome.storage.local.set({run});await tick();}}
  if(message.action==='open') {const {run}=await chrome.storage.local.get('run');if(run?.activeTab)await chrome.tabs.update(run.activeTab,{active:true});}
  if(message.action==='skip') {
    const {run}=await chrome.storage.local.get('run');
    if(run?.phase==='paused') {
      const task=run.queue[0]||run.details[0];run.errors[task.platform]=true;
      if(run.queue.length)run.queue.shift();else run.details.shift();
      // Leave a paused login/verification tab open for the user; never close it automatically.
      delete run.activeTab;run.phase='running';await chrome.storage.local.set({run});
    }
  }
  if(message.action==='stop') {const {run}=await chrome.storage.local.get('run');if(run){await chrome.storage.local.set({cancelledId:run.id});run.phase='stopped';run.message='已停止';await chrome.storage.local.set({run});}await chrome.storage.local.set({dailyEnabled:false});}
  if(message.action==='daily') {await chrome.storage.local.set({dailyEnabled:message.enabled===true,lastDay:day()});await ensureAlarm();}
  return {ok:true};
}
chrome.alarms.onAlarm.addListener(a=>{if(a.name==='01-tick')tick();});
chrome.runtime.onStartup.addListener(()=>ensureAlarm());
chrome.runtime.onInstalled.addListener(()=>ensureAlarm());
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(sender.id!==chrome.runtime.id||sender.url!==chrome.runtime.getURL('popup.html'))return false;
  command(message).then(reply,error=>reply({error:error.message}));return true;
});
chrome.storage.local.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'}).catch(()=>{});
ensureAlarm();
if(typeof module!=='undefined')module.exports={allowedUrl,day,tick,start,command,readTab};
