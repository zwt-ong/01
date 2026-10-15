/* Normal DOM only. Never read cookies, hidden app state, comments, or AI chapter summaries. */
function readRadarPage() {
  const text = el => (el?.innerText || el?.textContent || '').trim();
  const visible = el => !!el && el.getClientRects().length > 0;
  const host = location.hostname;
  const platform = host.endsWith('.bilibili.com') ? 'B站' : host === 'www.douyin.com' ? '抖音' : '';
  if (!platform) return {error:'页面不在支持范围内',items:[]};
  const body = document.body.innerText;
  if (/手机刷脸验证|请完成安全验证|拖动滑块|请完成验证|验证失败|访问受限/.test(body)) return {blocked:true,error:'需要本人完成平台验证',items:[]};
  if (platform==='抖音' && /登录后即可搜索|扫码登录|验证码登录/.test(body)) return {blocked:true,error:'需要本人登录抖音',items:[]};
  const duration = s => {
    if (!/^\d{1,2}:\d{2}(?::\d{2})?$/.test(s||'')) return null;
    return s.split(':').reduce((n,v)=>n*60+Number(v),0);
  };
  const stamp = s => {
    const m=(s||'').match(/(20\d{2})[-/](\d{2})[-/](\d{2})\s+(\d{2}):(\d{2})(?::(\d{2}))?/);
    return m ? `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]||'00'}+08:00` : '';
  };
  const cleanUrl = u => {try {if(!u)return '';const p=new URL(u,location.href); return p.origin+p.pathname;}catch{return '';}};
  let items=[];
  if (host==='search.bilibili.com') {
    for (const card of document.querySelectorAll('.bili-video-card')) {
      if (!visible(card)) continue;
      items.push({platform,title:text(card.querySelector('h3')),url:cleanUrl(card.querySelector('a[href*="/video/BV"]')?.href),
        creator:text(card.querySelector('.bili-video-card__info--author')),creator_url:cleanUrl(card.querySelector('.bili-video-card__info--owner')?.href),
        published_label:text(card.querySelector('.bili-video-card__info--date')),duration_seconds:duration(text(card.querySelector('.bili-video-card__stats__duration')))});
    }
  } else if (host==='space.bilibili.com') {
    if (!location.pathname.includes('/upload')) return {error:'尚未进入本人投稿列表',items:[]};
    const creator=text(document.querySelector('.nickname')) || text(document.querySelector('.h-name')) || document.title.split('投稿视频')[0];
    for (const a of document.querySelectorAll('a[href*="/video/BV"]')) {
      const title=a.getAttribute('title')||text(a);
      if (!visible(a) || !title || /^\d+[\s\d.万]*\n/.test(title)) continue;
      items.push({platform,title,url:cleanUrl(a.href),creator,creator_url:`https://space.bilibili.com/${location.pathname.split('/')[1]}`});
    }
  } else if (host==='www.bilibili.com' && /^\/video\/BV/.test(location.pathname)) {
    const author=document.querySelector('.up-name');
    const date=Array.from(document.querySelectorAll('span')).find(el=>visible(el)&&/^20\d\d-\d\d-\d\d \d\d:\d\d/.test(text(el)));
    items.push({platform,title:text(document.querySelector('h1')),url:cleanUrl(location.href),creator:text(author),creator_url:cleanUrl(author?.href),published:stamp(text(date)),excerpt:text(document.querySelector('#v_desc')).slice(0,400)});
  } else if (platform==='抖音' && location.pathname.startsWith('/search/')) {
    for (const a of document.querySelectorAll('a[href*="/video/"]')) {
      if (!visible(a)) continue;
      items.push({platform,title:text(a.querySelector('.VDYK8Xd7')),url:cleanUrl(a.href),creator:text(a.querySelector('.MZNczJmS')),
        published_label:text(a.querySelector('.faDtinfi')),duration_seconds:duration(text(a.querySelector('.ckopQfVu')))});
    }
  } else if (platform==='抖音' && location.pathname.startsWith('/user/')) {
    if (document.querySelector('#semiTabpost')?.getAttribute('aria-selected')!=='true') return {error:'尚未选中本人作品',items:[]};
    const creator=text(document.querySelector('h1'));
    for (const a of document.querySelectorAll('ul[data-e2e="scroll-list"] a[href*="/video/"]')) {
      if (!visible(a)) continue;
      items.push({platform,title:text(a.querySelector('p.frUrWD64'))||text(a.querySelector('p')),url:cleanUrl(a.href),creator,creator_url:cleanUrl(location.href)});
    }
  } else if (platform==='抖音' && /^\/video\/\d+$/.test(location.pathname)) {
    const author=Array.from(document.querySelectorAll('a[href*="/user/"]')).find(a=>a.querySelector('[data-click-from="title"]'));
    items.push({platform,title:text(document.querySelector('h1')),url:cleanUrl(location.href),creator:text(author),creator_url:cleanUrl(author?.href),
      published:stamp(text(document.querySelector('[data-e2e="detail-video-publish-time"]')))});
  }
  const unique=new Map();
  for(const item of items)if(item.url&&item.title&&item.creator&&!unique.has(item.url))unique.set(item.url,item);
  return {platform,items:[...unique.values()].slice(0,20),error:unique.size?'':'页面未读到作品；可能尚在加载、没有结果或页面结构发生变化'};
}
async function prepareRadarPage(kind) {
  const visible=el=>el.getClientRects().length>0;
  const leaf=t=>Array.from(document.querySelectorAll('span,div,a')).find(el=>visible(el)&&el.children.length===0&&el.textContent.trim()===t);
  if (kind==='creator' && location.hostname==='space.bilibili.com' && !location.pathname.includes('/upload')) {
    const entry=Array.from(document.querySelectorAll('a[href$="/upload"]')).find(visible);
    if (entry) entry.click();
  }
  if (kind==='search' && location.hostname==='www.douyin.com') {
    leaf('筛选')?.click();
    await new Promise(resolve=>setTimeout(resolve,500));
    leaf('最新发布')?.click();
    await new Promise(resolve=>setTimeout(resolve,500));
    leaf('一周内')?.click();
    await new Promise(resolve=>setTimeout(resolve,500));
    const latest=leaf('最新发布'),week=leaf('一周内');
    const selected=latest && Array.from(latest.classList).slice(1);
    if (!latest || !week || !selected.length || !selected.some(c=>week.classList.contains(c))) throw new Error('未能确认最新发布和一周内筛选，已停止');
    leaf('筛选')?.click();
  }
}
if (typeof module!=='undefined') module.exports={readRadarPage,prepareRadarPage};
