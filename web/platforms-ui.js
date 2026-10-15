"use strict";
function platformDuration(seconds) {
  const n=Math.max(0,Math.floor(Number(seconds)||0));
  return `${Math.floor(n/60)} 分 ${n%60} 秒`;
}
function browserHelperPanel(platform) {
  const browser=platform.browser||{items:[],statuses:[]};
  return `<section class="paper settings-panel"><h3>浏览器采集助手 · 待首次安装验收</h3><p class="muted">在 Edge 或 Chrome 中安装本地助手后，可读取关键词搜索与已绑定作者的作品。浏览器及 01 需要运行，遇到登录或验证暂停。每平台每轮最多读取 10 条详情；读取资料不等于已观看视频。</p><p><a href="/browser-helper.zip" download>下载浏览器助手源码包 ↓</a> · <a href="/browser-helper-guide" target="_blank" rel="noopener">查看安装步骤 ↗</a></p><p class="muted" id="browser-pair-state">${browser.paired?'已配对 '+h(browser.origin)+'；是否正在运行，请查看助手窗口。':'尚未配对，自动采集尚未开始。'}</p><form id="browser-pair-form"><label>助手窗口显示的扩展 ID<input name="extension_id" pattern="[a-p]{32}" minlength="32" maxlength="32" required autocomplete="off" placeholder="32 位小写字母"></label><button type="submit" class="button small">生成本地配对码</button><p class="muted small">配对只允许该助手向本机提交作品资料，不提供 YouTube 密钥、原文笔记或其他管理操作。</p></form><div id="browser-pair-result" hidden><label>配对码：仅复制到助手，勿发到聊天或 GitHub<input id="browser-pair-token" type="password" readonly autocomplete="off"></label><button type="button" class="button small" id="browser-copy-token">复制配对码</button></div><button type="button" class="button small" id="browser-revoke" ${browser.paired?'':'disabled'}>撤销助手配对</button><div>${(browser.statuses||[]).map(row=>`<p class="muted small">${h(row.name)}：${h(row.message)} · ${h(row.checked||'')}</p>`).join('')}</div><h4>浏览器已收集的作品 · 最多显示 60 条</h4><p class="muted small">有原始时间的资料将在更新日报后参加七天筛选；日期未知先留在这里。不把平台生成的 AI 章节摘要当作作者原话。</p>${(browser.items||[]).slice(0,60).map(row=>`<p><a href="${h(row.url)}" target="_blank" rel="noopener noreferrer">${h(row.title)} ↗</a><br><span class="muted small">${h(row.platform)} · ${h(row.creator)} · ${row.timestamp_kind==='published'?h(row.published):'原始日期未知'}</span></p>`).join('')||'<p class="muted">尚未收到浏览器资料。</p>'}</section>`;
}
function platformsView() {
  const platform=state.platforms||{queries:[],creators:[],capability:""};
  const creators=platform.creators||[];
  return `<div class="view-top"><p>先从你熟悉的中文原作出发，关注 vibe coding 的实践、复盘与产品验证。</p></div>
  <section class="paper settings-panel"><h3>本轮可用能力</h3><p class="muted">${h(platform.capability)}</p><p class="muted">资料读取不等于观看视频。没有字幕时先保留为候选；只有核对原作、补充原文后才整理观点。</p></section>
  ${browserHelperPanel(platform)}
  <section class="paper settings-panel"><form id="platform-import-form"><h3>收集抖音 / B站作品</h3><p class="muted">在软件里复制分享链接或文案，粘贴到这里，每次一条。B站可尝试读取标题、作者、原始时间和时长；抖音暂保存链接，信息待补。</p><label>作品链接或分享文案<textarea name="share_text" rows="3" maxlength="5000" required placeholder="粘贴包含 https://b23.tv/…、B站视频地址或抖音分享链接的文案"></textarea></label><label>标题（可选；未读到资料时使用）<input name="title" maxlength="240"></label><label>提出者（可选；仍需核对本人原作）<input name="creator" maxlength="100"></label><button type="submit" class="button primary">读取资料并加入观察</button><p class="muted small">原始时间未知的内容不会进入七天新内容；旧作品可保留为参考。导入完成后，到“我的观察”补字幕和六字段。</p></form></section>
  <section class="paper settings-panel"><h3>发现陌生作者</h3><p class="muted">点击后在平台搜索，再把值得阅读的作品分享进来。这些按钮是手动搜索入口；自动读取需使用上方已配对的浏览器助手。</p><div class="sources-grid">${platform.queries.map(row=>`<div class="source-card"><strong>${h(row.query)}</strong><div class="idea-actions"><a href="${h(row.bilibili)}" target="_blank" rel="noopener noreferrer">去 B站搜索 ↗</a><a href="${h(row.douyin)}" target="_blank" rel="noopener noreferrer">去抖音搜索 ↗</a></div></div>`).join("")}</div><form id="platform-query-form"><label>搜索方向，每行一个，最多 6 个<textarea name="queries" rows="3" maxlength="606" required>${h(platform.queries.map(row=>row.query).join("\n"))}</textarea></label><button type="submit" class="button small">保存中文搜索方向</button></form></section>
  <section class="paper settings-panel"><form id="creator-watchlist-form"><h3>参考作者与追新入口</h3><p class="muted">先确认本人主页。姓名搜索可能包含同名、切片或搬运账号，不能据此确认原作。填写本人主页后，已配对的浏览器助手可读取其作品列表；未运行助手时可手动查看主页。</p><div class="sources-grid">${creators.map(row=>`<div class="source-card" data-creator-row><label>作者名称<input name="name" value="${h(row.name)}" maxlength="100" required></label><div class="idea-actions"><a href="${h(row.bilibili)}" target="_blank" rel="noopener noreferrer">在 B站找本人 ↗</a><a href="${h(row.douyin)}" target="_blank" rel="noopener noreferrer">在抖音找本人 ↗</a></div><label>B站本人主页<input name="bilibili_url" type="url" value="${h(row.bilibili_url||"")}" placeholder="https://space.bilibili.com/…"></label><label>抖音本人主页<input name="douyin_url" type="url" value="${h(row.douyin_url||"")}" placeholder="https://www.douyin.com/user/…"></label>${row.bilibili_url||row.douyin_url?`<div class="idea-actions">${row.bilibili_url?`<a href="${h(row.bilibili_url)}" target="_blank" rel="noopener noreferrer">打开 B站主页 ↗</a>`:""}${row.douyin_url?`<a href="${h(row.douyin_url)}" target="_blank" rel="noopener noreferrer">打开抖音主页 ↗</a>`:""}</div>`:'<p class="muted small">尚未绑定本人主页</p>'}</div>`).join("")}</div><label>新增参考作者，每行一个<textarea name="new_names" rows="2" maxlength="1000" placeholder="填你希望持续关注的作者名称"></textarea></label><button type="submit" class="button small">保存作者与主页</button><p class="muted small">参考作者及主页配置仅保存在本地。</p></form></section>`;
}

document.addEventListener("submit",async(event)=>{
  if(!["platform-import-form","platform-query-form","creator-watchlist-form"].includes(event.target.id))return;
  event.preventDefault();const form=event.target;const button=form.querySelector('button[type="submit"]');button.disabled=true;
  try{
    if(form.id==="platform-import-form"){
      const result=await api("/api/platform-import",Object.fromEntries(new FormData(form)));
      view="saved";await load();toast(result.message);
    }
    if(form.id==="platform-query-form"){
      await api("/api/settings",{platform_queries:form.elements.queries.value.split("\n").map(s=>s.trim()).filter(Boolean)});
      await load();toast("中文搜索方向已保存");
    }
    if(form.id==="creator-watchlist-form"){
      const rows=[...form.querySelectorAll("[data-creator-row]")].map(row=>Object.fromEntries(["name","bilibili_url","douyin_url"].map(key=>[key,row.querySelector(`[name=${key}]`).value.trim()])));
      const names=form.elements.new_names.value.split("\n").map(s=>s.trim()).filter(Boolean);
      for(const name of names){if(!rows.some(row=>row.name===name))rows.push({name,bilibili_url:"",douyin_url:""});}
      await api("/api/settings",{creator_watchlist:rows});await load();toast("参考作者和主页入口已保存");
    }
  }catch(error){toast(error.message);}finally{button.disabled=false;}
});

document.addEventListener("submit",async event=>{
  if(event.target.id!=="browser-pair-form")return;
  event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;
  try{const result=await api('/api/browser-pair',{extension_id:event.target.elements.extension_id.value.trim()});document.querySelector('#browser-pair-result').hidden=false;document.querySelector('#browser-pair-token').value=result.token;document.querySelector('#browser-revoke').disabled=false;document.querySelector('#browser-pair-state').textContent='配对码已生成，请在助手窗口完成配对；自动采集尚未开始。';toast('配对码已生成，请复制到助手');}catch(error){toast(error.message);}finally{button.disabled=false;}
});
document.addEventListener('click',async event=>{
  if(event.target.id==='browser-copy-token'){try{await navigator.clipboard.writeText(document.querySelector('#browser-pair-token').value);toast('配对码已复制，请仅粘贴到助手');}catch{toast('请手动选择并复制配对码');}}
  if(event.target.id==='browser-revoke'){try{await api('/api/browser-pair',{disable:true});await load();toast('助手配对已撤销');}catch(error){toast(error.message);}}
});
