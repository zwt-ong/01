"use strict";
let state = null;
let view = "dashboard";
let filter = "all";
let search = "";
let reportId = null;
let pollTimer = null;
let toastTimer = null;
const $ = (selector) => document.querySelector(selector);
const h = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
const labels = {ai:"AI",creator:"个人 IP",business:"商业应用"};
const date = (value, full=false) => new Intl.DateTimeFormat("zh-CN", {timeZone:"Asia/Shanghai",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",...(full?{year:"numeric"}:{})}).format(new Date(value));
const saved = (id) => state.saved.some((item) => item.id === id);
function toast(message) { $("#toast").textContent=message; $("#toast").classList.add("visible"); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$("#toast").classList.remove("visible"),3500); }
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method:"POST",headers:{"Content-Type":"application/json","X-Radar-Token":state.token},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "操作失败，请重试");
  return result;
}
async function load(render=true) {
  try {
    state = await api("/api/state"+(reportId?"?report="+encodeURIComponent(reportId):""));
    if(render) renderPage();
    clearTimeout(pollTimer);
    if(state.job.running) pollTimer=setTimeout(()=>load(),1800);
  } catch(error) {
    $("#notice").innerHTML=`<div class="notice warn">无法连接本地服务：${h(error.message)}。请确认启动窗口仍在运行。</div>`;
    $("#refresh").disabled=false;
  }
}
function empty(title, text, button=false) {
  return `<div class="empty"><h3>${h(title)}</h3><div>${h(text)}</div>${button?'<button class="button primary" data-action="refresh">生成第一份日报</button>':""}</div>`;
}
function article(item, index, inSaved=false) {
  const title=item.title_zh || item.title;
  const tags=item.tags || [];
  return `<article class="article"><span class="article-number">${String(index+1).padStart(2,"0")}</span><div><div class="article-top"><span class="source">${h(item.source_name)}</span>${tags.map(tag=>`<span class="pill ${tag==="business"?"amber":""}">${h(labels[tag])}</span>`).join("")}${item.translation_state?.includes("未完成")?'<span class="pill gray">英文原文</span>':""}${item.source_id==="manual"?'<span class="pill amber">用户提供 · 未核实</span>':""}</div><h3><a href="${h(item.url)}" target="_blank" rel="noopener noreferrer">${h(title)} ↗</a></h3><p class="excerpt">${h(item.excerpt_zh ?? item.excerpt) || "订阅源未提供摘要，请打开原文核实。"}</p><div class="article-footer"><span>${h(date(item.published))} · 北京时间</span><span>${h(item.summary_kind || "用户摘录")}</span><button class="text-button ${saved(item.id)?"saved":""}" data-save="${h(item.id)}">${saved(item.id)?"★ 已观察":"☆ 加入观察"}</button>${inSaved?`<button class="text-button" data-note="${h(item.id)}">记录验证</button>`:""}</div>${item.language==="en"?`<details class="original"><summary>原文与翻译说明</summary><p>${h(item.title)}</p><p>${h(item.translation_state || "保留英文原文")}。机器翻译仅供理解，事实以原文为准。</p></details>`:""}${item.related_sources?.length?`<details class="original"><summary>其他来源（${item.related_sources.length}）</summary>${item.related_sources.map(s=>`<p><a href="${h(s.url)}" target="_blank" rel="noopener noreferrer">${h(s.name)} ↗</a></p>`).join("")}</details>`:""}${inSaved&&item.note?`<div class="saved-note">${h(item.note)}</div>`:""}</div></article>`;
}
function opportunity(card, index) {
  return `<article class="opportunity"><div class="micro">SIGNAL ${String(index+1).padStart(2,"0")}</div><h3>${h(card.title)}</h3><p>${h(card.hypothesis)}</p><span class="pill">${h(card.status)} · ${h(card.confidence)}</span><details><summary>查看证据与验证动作 →</summary><p><strong>已有线索</strong> · ${h(card.evidence_kind)}</p>${card.evidence.map(item=>`<a class="evidence" href="${h(item.url)}" target="_blank" rel="noopener noreferrer">${h(item.title)} ↗<small>${h(item.source)} · ${h(date(item.published))}</small></a>`).join("")}<p><strong>还缺什么</strong><br>${h(card.missing)}</p><p><strong>今天可以做</strong><br>${h(card.action)}</p><p><strong>继续或暂缓的条件</strong><br>${h(card.success)}</p><p>${h(card.time_budget)} · ${h(card.spend)}</p></details></article>`;
}
function dashboard() {
  const report = state.report;
  if(!report) return `<div class="paper">${empty("从第一份日报开始", "读取公开订阅源，整理过去 24 小时的变化。通常需要约 1～2 分钟。", !state.job.running)}</div>`;
  const items=report.items.filter(item=>(filter==="all"||item.tags.includes(filter))&&(!search||(item.title_zh+item.title+item.excerpt_zh+item.source_name).toLowerCase().includes(search.toLowerCase())));
  return `<div class="stats"><div class="stat"><span class="stat-icon">▤</span><div><div class="stat-number">${report.items.length}<small> 条</small></div><div class="stat-label">本期精选 · ${report.candidate_count} 条相关内容</div></div></div><div class="stat"><span class="stat-icon">↗</span><div><div class="stat-number">${report.opportunities.length}<small> 个</small></div><div class="stat-label">候选机会 · 等待你的验证</div></div></div><div class="stat"><span class="stat-icon">◎</span><div><div class="stat-number">${report.source_success}<small> / ${report.source_total}</small></div><div class="stat-label">信息源读取成功</div></div></div></div><div class="section-head"><div class="section-title"><span>↗</span>机会观察<span class="section-subtitle">关注变化，更关注谁愿意为问题付费</span></div><span class="pill gray">商业假设 · 非结论</span></div>${report.opportunities.length?`<div class="opportunity-grid">${report.opportunities.map(opportunity).join("")}</div>`:`<div class="quiet-state"><span class="quiet-icon">◎</span><div><strong>本期暂未出现足够的机会证据</strong>继续观察重复需求、真实使用和付费意愿。没有用热点填充机会卡。</div></div>`}<div class="dashboard-columns"><section><div class="section-head"><div class="section-title"><span>▤</span>${h(report.label)}<span class="section-subtitle">按相关度与新鲜度排序</span></div><a class="section-link" href="/api/export?report=${encodeURIComponent(report.id)}">导出日报 ↓</a></div><div class="paper"><div class="toolbar">${["all","business","ai","creator"].map(tag=>`<button class="filter ${filter===tag?"active":""}" data-filter="${tag}">${tag==="all"?"全部动态":labels[tag]}</button>`).join("")}<label class="search"><input id="search" aria-label="搜索日报" placeholder="搜索标题、来源…" value="${h(search)}"></label></div><div id="article-list">${items.length?items.map((item,index)=>article(item,index)).join(""):empty(report.items.length?"没有匹配的内容":"本期没有新内容",report.items.length?"换一个关键词或筛选方向试试。":"查看信息源状态，确认网络是否可用；历史内容仍可在历史日报中查看。")}</div></div><div class="section-head"><span class="report-meta">覆盖 ${h(date(report.start))} — ${h(date(report.end))} · 北京时间</span><span class="report-meta">更新于 ${h(date(report.created))}</span></div></section><aside class="right-panel"><div class="schedule-card"><div class="small-label">下一份完整日报</div><div class="schedule-time">00:00<small>北京时间</small></div><p>整理刚结束的 24 小时。程序运行时自动更新，错过后启动会补跑。</p><div class="section-head"><div class="section-title">信息源概览</div><button class="section-link" data-view="sources">管理 →</button></div>${state.sources.filter(s=>s.enabled).map(s=>`<div class="source-row"><span><i class="dot ${s.status?.ok===false?"failed":""}"></i>${h(s.name)}</span><span>${s.status?s.status.ok?"已连接":"暂不可用":"等待采集"}</span></div>`).join("")}</div><div class="method-card"><h3>把线索变成下一步</h3><div class="method-step"><span>1</span>确认具体的人与问题</div><div class="method-step"><span>2</span>用样例测试真实需求</div><div class="method-step"><span>3</span>记录反馈，再决定投入</div><p>每天两小时，先完成一个小验证。预算未定时，先访谈、做样例。</p><button class="button small" data-action="manual">＋ 添加你的观察</button></div></aside></div>`;
}
function historyView() {
  if(!state.history.length)return `<div class="paper">${empty("还没有历史日报","生成第一份日报后，这里会保存每次更新的记录。",true)}</div>`;
  return `<div class="view-top"><p>最近 ${state.history.length} 份记录 · 数据仅保存在本地</p></div><div class="history-list">${state.history.map(report=>`<article class="paper history-card"><div><h3>${h(report.scheduled?report.label:report.id.replace("-live", "")+" · 实时简报")}</h3><p>${h(date(report.start,true))} — ${h(date(report.end,true))} · ${report.item_count} 条内容 · ${report.source_success}/${report.source_total} 个来源成功</p></div><button class="button small" data-report="${h(report.id)}">查看日报 ↗</button></article>`).join("")}</div>`;
}
function savedView() {
  return `<div class="view-top"><p>把值得追踪的内容留下来，再记录真实反馈。</p><button class="button small" data-action="manual">＋ 添加链接</button></div><div class="paper">${state.saved.length?state.saved.map((item,index)=>article(item,index,true)).join(""):empty("观察清单还是空的","点击日报中的“加入观察”，或手动添加一条链接。")}</div>`;
}
function sourcesView() {
  return `<div class="view-top"><p>优先稳定、公开的信息源。关闭来源后，下次更新生效。</p></div><div class="sources-grid">${state.sources.map(source=>`<article class="source-card"><div class="source-card-top"><h3>${h(source.name)}</h3><label class="toggle"><input type="checkbox" data-source="${h(source.id)}" aria-label="启用${h(source.name)}" ${source.enabled?"checked":""}><span></span></label></div><p>${h(source.kind)} · ${source.language==="en"?"英文 → 中文":"中文"}</p><a href="${h(source.url)}" target="_blank" rel="noopener noreferrer">查看公开订阅源 ↗</a><div class="source-result ${source.status?.ok===false?"error":""}">${!source.enabled?h(source.disabled_reason||"已停用"):source.status?source.status.ok?`采集成功 · ${source.status.count} 条可用内容 · ${h(date(source.status.checked_at))}`:`暂不可用 · ${h(source.status.message)}`:"尚未采集"}</div></article>`).join("")}</div><section class="paper settings-panel"><div class="settings-row"><div><strong>免费英文翻译</strong><p>英文标题与短摘录会发送给 MyMemory 公共翻译服务；本地每日最多使用 4,000 字符。失败或额度不足时保留原文。</p></div><label class="toggle"><input type="checkbox" id="translation-toggle" aria-label="启用免费英文翻译" ${state.settings.translation_enabled?"checked":""}><span></span></label></div></section><section class="paper settings-panel"><strong>当前版本的覆盖范围</strong><p class="muted">已接入公开资讯订阅源与 YouTube 官方博客；尚未自动搜索 YouTube 视频，也未接入抖音、TikTok 热榜。你可以先手动添加这些平台的链接。</p><p class="muted">摘要来自订阅源短摘录，没有调用大模型。排序依据是兴趣相关度与发布时间；不会把它称为全网热度排名。</p><p class="muted">个人配置、收藏、验证笔记和日报保存在本地，均已从 GitHub 提交范围排除。</p></section>`;
}
function renderPage() {
  const headings = {dashboard:["先看到变化，再验证机会。","把 AI、创作与商业信号，整理成值得你行动的线索。"],history:["让变化留下轨迹。","回看过去的日报，识别持续出现的信号。"],saved:["值得观察的，值得验证。","记录你的问题、试验和反馈，把信息变成经验。"],sources:["好判断，从好来源开始。","了解信息从哪里来，也了解它的边界。"]};
  $("#page-title").textContent=headings[view][0];$("#page-subtitle").textContent=headings[view][1];
  document.querySelectorAll(".nav-item").forEach(button=>{const active=button.dataset.view===view;button.classList.toggle("active",active);button.setAttribute("aria-current",active?"page":"false");});
  $("#saved-count").textContent=state.saved.length;
  $("#clock").textContent=date(state.now,true)+" · 北京时间";
  $("#refresh").disabled=state.job.running;
  $("#refresh-label").textContent=state.job.running?"正在更新…":"更新日报";
  const notices=[];
  if(state.job.running)notices.push(`<div class="notice">${h(state.job.message)}。你可以继续浏览已有日报。</div>`);
  if(state.job.error)notices.push(`<div class="notice warn">${h(state.job.error)}</div>`);
  if(view==="dashboard"&&state.report){
    state.report.warnings.forEach(message=>notices.push(`<div class="notice warn">${h(message)}</div>`));
    if(state.report.partial)notices.push('<div class="notice warn">部分来源采集失败，本期覆盖不完整。请在“信息源与设置”查看详情。</div>');
    if(state.report.translation_error)notices.push('<div class="notice warn">免费翻译暂不可用，部分英文内容保留原文。</div>');
  }
  $("#notice").innerHTML=notices.join("");
  $("#content").innerHTML=({dashboard,history:historyView,saved:savedView,sources:sourcesView}[view])();
}
document.addEventListener("click",async(event)=>{
  const button=event.target.closest("button,a[data-view]");if(!button)return;
  try{
    if(button.dataset.view){view=button.dataset.view;renderPage();}
    if(button.dataset.filter){filter=button.dataset.filter;renderPage();}
    if(button.id==="refresh"||button.dataset.action==="refresh"){reportId=null;await api("/api/refresh",{});await load();}
    if(button.dataset.report){reportId=button.dataset.report;view="dashboard";await load();}
    if(button.dataset.save){const id=button.dataset.save;const remove=saved(id);await api("/api/save",{id,remove});await load();toast(remove?"已移出观察清单":"已加入观察清单");}
    if(button.dataset.action==="manual")$("#manual-dialog").showModal();
    if(button.dataset.close)document.getElementById(button.dataset.close).close();
    if(button.dataset.note){const item=state.saved.find(item=>item.id===button.dataset.note);$("#note-form [name=id]").value=item.id;$("#note-form [name=note]").value=item.note;$("#note-title").textContent=item.title_zh||item.title;$("#note-dialog").showModal();}
  }catch(error){toast(error.message);}
});
document.addEventListener("input",event=>{
  if(event.target.id!=="search")return;
  search=event.target.value;
  const items=state.report.items.filter(item=>(filter==="all"||item.tags.includes(filter))&&(!search||(item.title_zh+item.title+item.excerpt_zh+item.source_name).toLowerCase().includes(search.toLowerCase())));
  $("#article-list").innerHTML=items.length?items.map((item,index)=>article(item,index)).join(""):empty("没有匹配的内容","换一个关键词或筛选方向试试。");
});
document.addEventListener("change",async(event)=>{
  try{
    if(event.target.dataset.source){await api("/api/settings",{source_id:event.target.dataset.source,enabled:event.target.checked});await load();toast("信息源设置已保存，下次更新生效");}
    if(event.target.id==="translation-toggle"){await api("/api/settings",{translation_enabled:event.target.checked});await load();toast("翻译设置已保存");}
  }catch(error){toast(error.message);await load();}
});
$("#manual-form").addEventListener("submit",async(event)=>{
  event.preventDefault();const form=event.target;const body=Object.fromEntries(new FormData(form));if(body.published)body.published += ":00+08:00";
  try{await api("/api/manual",body);$("#manual-dialog").close();form.reset();view="saved";await load();toast("已加入观察；下次更新会尝试纳入日报");}catch(error){toast(error.message);}
});
$("#note-form").addEventListener("submit",async(event)=>{
  event.preventDefault();try{await api("/api/save",Object.fromEntries(new FormData(event.target)));$("#note-dialog").close();await load();toast("验证记录已保存");}catch(error){toast(error.message);}
});
load();
