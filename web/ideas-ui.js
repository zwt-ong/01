"use strict";
function filteredIdeas(candidates) {
  return (state.report?.items || []).filter(item => (candidates || item.idea) && (filter==="all" || item.tags?.includes(filter)) && (!search || [item.title_zh,item.title,item.creator,item.excerpt_zh,item.idea?.claim].join(" ").toLowerCase().includes(search.toLowerCase())));
}
function ideaArticle(item,index,inSaved=false) {
  const idea=item.idea;
  const published=item.timestamp_kind==="added"?"原始发布时间待核对":date(item.published,true)+" · 北京时间";
  return `<article class="article idea-card"><span class="article-number">${String(index+1).padStart(2,"0")}</span><div><div class="article-top"><span class="source">${h(item.creator||"提出者待核对")}</span><span class="pill gray">${h(item.platform||item.source_name)}</span>${item.discovered_today?'<span class="pill">今日首次发现</span>':""}${idea?`<span class="pill">${h(idea.status)}</span>`:`<span class="pill gray">${h(item.analysis_status||"待阅读原作")}</span>`}</div><h3><a href="${h(item.url)}" target="_blank" rel="noopener noreferrer">${h(item.title_zh||item.title)} ↗</a></h3>${idea?`<dl class="idea-fields"><dt>谁提出</dt><dd>${h(item.creator)}</dd><dt>核心观点</dt><dd>${h(idea.claim)}</dd><dt>有什么新意</dt><dd><span class="pill gray">${h(idea.novelty_type)}</span> ${h(idea.novelty)}<small>相对差异待核对，不代表世界首创。</small></dd><dt>依据或实践经历</dt><dd>${h(idea.evidence)}<blockquote>${h(idea.quote)}</blockquote></dd><dt>原始时间与链接</dt><dd>${h(published)} · <a href="${h(item.url)}" target="_blank" rel="noopener noreferrer">打开本人原作 ↗</a></dd><dt>可以怎样验证或使用</dt><dd>${h(idea.use)}<small>验证建议；不是作者已完成的实验或收益保证。</small></dd></dl>`:`<p class="excerpt">${h(item.excerpt_zh||item.excerpt)||"尚无可读原文。补充字幕或作者原文后再整理。"}</p><p class="candidate-note">${h(item.body_kind||"用户摘录")}${Number.isFinite(item.duration_seconds)?" · 时长 "+h(platformDuration(item.duration_seconds)):""} · ${item.primary_confirmed?"个人原始发布页面":"上传者与观点提出者尚待核对"}。新意、说服力和可实践性尚未评估。</p>`}${item.commercial_note?`<p class="candidate-note">${h(item.commercial_note)}</p>`:""}<div class="article-footer"><span>${h(published)}</span><span>首次发现 ${item.first_seen?h(date(item.first_seen,true)):"历史时间未知"}</span></div><div class="idea-actions"><button class="text-button" data-review="${h(item.id)}">${idea?"核对 / 编辑观点":"补原文 / 整理观点"}</button><button class="text-button" data-save="${h(item.id)}">${saved(item.id)?"★ 已观察":"☆ 加入观察"}</button>${inSaved?`<button class="text-button" data-note="${h(item.id)}">记录验证</button>`:""}${item.creator_id?`<button class="text-button" data-block="${h(item.id)}">屏蔽作者</button>`:""}</div>${inSaved&&item.note?`<div class="saved-note">${h(item.note)}</div>`:""}${item.language==="en"?`<details class="original"><summary>英文原文标题</summary><p>${h(item.title)}</p><p>译文可能不完整，请核对本人原作。</p></details>`:""}</div></article>`;
}
function ideasDashboard(candidates) {
  const report=state.report;
  if(!report||report.profile!=="creator-ideas-v2")return `<div class="paper">${empty("生成第一份原创观点日报","读取个人原始博客。自动发现 YouTube 陌生创作者需先配置免费密钥。",true)}</div>`;
  const items=filteredIdeas(candidates), ready=report.items.filter(item=>item.idea).length;
  return `<div class="stats"><div class="stat"><span class="stat-icon">◎</span><div><div class="stat-number">${ready}<small> 张</small></div><div class="stat-label">有原文依据的观点卡</div></div></div><div class="stat"><span class="stat-icon">↗</span><div><div class="stat-number">${report.items.length}<small> 条</small></div><div class="stat-label">展示候选 / 共 ${report.candidate_count} 条初筛</div></div></div><div class="stat"><span class="stat-icon">＋</span><div><div class="stat-number">${report.items.filter(item=>item.discovered_today).length}<small> 条</small></div><div class="stat-label">展示内容中今日首次发现</div></div></div></div><div class="section-head"><div class="section-title">${candidates?"发现候选":"六字段观点卡"}<span class="section-subtitle">按今日首次发现、兴趣相关度与发布时间排序</span></div><a class="section-link" href="/api/export?report=${encodeURIComponent(report.id)}">导出日报 ↓</a></div>${!candidates&&!ready?`<div class="quiet-state"><div><strong>本期候选还没有完成观点整理</strong><p>先阅读原作，再补充原文或字幕。有依据后生成六字段；模型结果仍需核对。</p><button class="button small" data-view="candidates">查看 ${report.items.length} 条候选 →</button></div></div>`:""}<div class="paper"><div class="toolbar">${["all","ai","creator","business","cross"].map(tag=>`<button class="filter ${filter===tag?"active":""}" data-filter="${tag}">${tag==="all"?"全部":h(labels[tag])}</button>`).join("")}<label class="search"><input id="search" aria-label="搜索观点或作者" placeholder="搜索观点、作者…" value="${h(search)}"></label></div><div id="article-list">${items.length?items.map((item,index)=>ideaArticle(item,index)).join(""):empty(candidates?"本期没有候选":"这里将显示整理完成的观点","只纳入最近 7 天发布的原作；没有新内容时保留空状态。")}</div></div><div class="section-head"><span class="report-meta">原始发布范围 ${h(date(report.start,true))} — ${h(date(report.end,true))}</span><span class="report-meta">每天 00:00 更新 · 北京时间</span></div>${Object.keys(report.excluded||{}).length?`<p class="muted small">本期过滤：${Object.entries(report.excluded).map(([key,value])=>h(key)+" "+value+" 条").join("；")}</p>`:""}<div class="paper settings-panel"><strong>本期覆盖</strong><p class="muted">${report.source_status.map(source=>h(source.name)+"："+h(source.message)).join("；")}</p><p class="muted">抖音 / B站可安装本地浏览器助手读取关键词搜索与本人作品，需在浏览器中配对并完成首次验收；未运行助手时不自动采集。小红书仍支持手动链接。</p><button class="button small" data-view="platforms">去抖音 / B站工作台</button><button class="button small" data-action="manual">＋ 添加本人原作</button></div>`;
}
function ideasSources() {
  return `<div class="view-top"><p>原来的媒体与营销资讯源已停用。博客作为可用的起点，YouTube 关键词发现可扩展陌生创作者。</p></div><div class="sources-grid">${state.sources.map(source=>`<article class="source-card"><div class="source-card-top"><h3>${h(source.name)}</h3><label class="toggle"><input type="checkbox" data-source="${h(source.id)}" aria-label="启用${h(source.name)}" ${source.enabled?"checked":""}><span></span></label></div><p>${h(source.kind)} · ${source.language==="en"?"英文 → 中文":"中文"}</p><a href="${h(source.url)}" target="_blank" rel="noopener noreferrer">查看作者订阅源 ↗</a><div class="source-result">${!source.enabled?"已停用":source.status?h(source.status.message):"等待采集"}</div></article>`).join("")}</div><section class="paper settings-panel"><form id="discovery-form"><h3>YouTube 自动发现</h3><p class="muted">${state.discovery.configured?"密钥已保存在本地。留空保留现有密钥。":"尚未配置免费 YouTube Data API 密钥。"} 每天最多 6 个关键词，每个取一页并缓存；不会按热门榜替代个人观点。</p><label class="check-label"><input name="enabled" type="checkbox" ${state.discovery.enabled?"checked":""}>启用陌生创作者搜索</label><label>API 密钥<input name="key" type="password" autocomplete="new-password" placeholder="仅填入本地页面，不发送到聊天或 GitHub"></label><label>搜索方向，每行一个，最多 6 个<textarea name="queries" rows="6" maxlength="606">${h(state.discovery.queries.join("\n"))}</textarea></label><div class="idea-actions"><button type="submit" class="button primary small">保存发现设置</button><button type="button" id="clear-key" class="text-button">删除本地密钥</button><a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noopener noreferrer">启用 YouTube Data API ↗</a></div></form></section><section class="paper settings-panel"><form id="model-form"><h3>免费本地模型</h3><p class="muted">仅连接本机 Ollama 的 11434 端口；不会自动安装或下载。视频没有字幕时仍留在候选，可自行补原文。最多分析本期展示的 30 条。</p><label class="check-label"><input name="enabled" type="checkbox" ${state.analysis.enabled?"checked":""}>启用原文观点整理</label><label>已安装的模型名<input name="model" value="${h(state.analysis.model)}" required></label><div class="idea-actions"><button type="submit" class="button primary small">保存模型设置</button><button type="button" id="check-model" class="button small">检测本地服务</button><a href="https://ollama.com/download/windows" target="_blank" rel="noopener noreferrer">Ollama 官方下载 ↗</a></div><p id="model-status" class="muted" role="status">尚未检测</p></form></section><section class="paper settings-panel"><div class="settings-row"><div><strong>免费英文标题与节选翻译</strong><p>公开标题与短摘录发送至 MyMemory；原文和个人笔记不发送。每日最多 4,000 字符，失败会保留英文。六字段由你或本地模型用中文整理。</p></div><label class="toggle"><input type="checkbox" id="translation-toggle" ${state.settings.translation_enabled?"checked":""}><span></span></label></div></section><section class="paper settings-panel"><h3>已屏蔽作者</h3>${state.blocked_creators.length?state.blocked_creators.map(creator=>`<div class="source-row"><span>${h(creator.id)}</span><button class="text-button" data-unblock="${h(creator.id)}">恢复</button></div>`).join(""):"<p class='muted'>暂无。发现候选中可以屏蔽作者，操作可撤销。</p>"}<p class="muted">本人发布不代表观点必然正确；引文核对不验证事实或证明收益。新意、说服力和实践价值需要阅读与使用反馈。</p></section>`;
}
function reviewValues() {
  const form=$("#review-form");
  return {...Object.fromEntries(new FormData(form)),primary_confirmed:form.elements.primary_confirmed.checked};
}
function fillReview(review) {
  const form=$("#review-form");
  for(const key of ["body","claim","novelty","evidence","quote","use","novelty_type","creator"]){if(review[key]!==undefined)form.elements[key].value=review[key];}
  if(review.primary_confirmed!==undefined)form.elements.primary_confirmed.checked=review.primary_confirmed;
}
document.addEventListener("click",async event=>{
  const button=event.target.closest("button");if(!button)return;
  try{
    if(button.dataset.review){
      const item=[...(state.report?.items||[]),...state.saved].find(item=>item.id===button.dataset.review);
      if(!item)return;
      const form=$("#review-form");form.reset();form.elements.id.value=item.id;form.elements.creator.value=item.creator==="待核对"?"":item.creator||"";
      $("#review-title").textContent=(item.title_zh||item.title)+" · 原始时间："+(item.timestamp_kind==="added"?"待核对":date(item.published,true));
      $("#review-progress").textContent="";
      const result=await api("/api/review?id="+encodeURIComponent(item.id));fillReview(result.review);
      $("#review-dialog").showModal();
    }
    if(button.dataset.block){await api("/api/block",{id:button.dataset.block});await load();toast("已屏蔽作者，可在设置中恢复");}
    if(button.dataset.unblock){await api("/api/unblock",{creator_id:button.dataset.unblock});await load();toast("已恢复作者");}
    if(button.id==="clear-key"){await api("/api/settings",{youtube_api_key:""});await load();toast("本地密钥已删除");}
    if(button.id==="check-model"){
      button.disabled=true;const status=await api("/api/model-status");$("#model-status").textContent=status.message+(status.models.length?" · "+status.models.join("、"):"");button.disabled=false;
    }
    if(button.id==="analyze-review"){
      const value=reviewValues();if(!value.primary_confirmed||!value.creator||value.body.length<250)throw new Error("先确认作者和本人原作，补充至少 250 字符原文或字幕。");
      button.disabled=true;$("#review-progress").textContent="本地模型正在整理并复核原文，首次加载可能较慢…";
      try{const result=await api("/api/review",{...value,action:"analyze"});fillReview(result.review);$("#review-progress").textContent="模型整理已保存为待核对。请阅读六字段，再点击底部确认。";await load(false);}finally{button.disabled=false;}
    }
  }catch(error){toast(error.message);if(button.id==="analyze-review")$("#review-progress").textContent=error.message;button.disabled=false;}
});
document.addEventListener("submit",async event=>{
  if(!["discovery-form","model-form","review-form"].includes(event.target.id))return;
  event.preventDefault();const form=event.target;const submit=form.querySelector('button[type="submit"]');submit.disabled=true;
  try{
    if(form.id==="discovery-form"){
      const body={youtube_discovery_enabled:form.elements.enabled.checked,discovery_queries:form.elements.queries.value.split("\n").map(s=>s.trim()).filter(Boolean)};
      if(form.elements.key.value.trim())body.youtube_api_key=form.elements.key.value.trim();
      await api("/api/settings",body);await load();toast("发现设置已保存，更新日报后生效");
    }
    if(form.id==="model-form"){await api("/api/settings",{local_model_enabled:form.elements.enabled.checked,local_model:form.elements.model.value});await load();toast("模型设置已保存");}
    if(form.id==="review-form"){await api("/api/review",reviewValues());$("#review-dialog").close();await load();toast("观点卡已保存，原文和笔记仅留本地");}
  }catch(error){toast(error.message);if(form.id==="review-form")$("#review-progress").textContent=error.message;}finally{submit.disabled=false;}
});
