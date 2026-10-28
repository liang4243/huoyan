// HUOYAN_DOM_BEGIN
function readFavorites() {
  const text=e=>(e?.innerText||e?.getAttribute('aria-label')||e?.title||'').replace(/[\ue000-\uf8ff]/g,'').replace(/\s+/g,' ').trim();
  const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>1&&r.height>1&&s.display!=='none'&&s.visibility!=='hidden';};
  const path=e=>{const p=[];for(;e&&e.nodeType===1;e=e.parentElement){if(e===document.documentElement){p.unshift('html');break;}p.unshift(e.tagName.toLowerCase()+':nth-child('+([...e.parentElement.children].indexOf(e)+1)+')');}return p.join(' > ');};
  const folderUrl=href=>{try{const u=new URL(href,location.href);return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&
    (u.hostname==='i.taobao.com'&&/^\/my_itaobao\/itao-tool\/collect\/?$/.test(u.pathname)||u.hostname==='shoucang.taobao.com'&&/^\/(?:item_collect(?:_new)?|favorite)\.htm$/.test(u.pathname));}catch{return false;}};
  const productUrl=href=>{try{const u=new URL(href,location.href);return u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&['item.taobao.com','detail.tmall.com'].includes(u.hostname)&&u.pathname==='/item.htm'&&/^\d+$/.test(u.searchParams.get('id')||'')?{productId:u.searchParams.get('id'),url:u.origin+u.pathname+'?id='+u.searchParams.get('id')}:null;}catch{return null;}};
  const product=productUrl(location.href),isFavoritesPage=folderUrl(location.href);
  const favoriteRoot=document.querySelector('[data-taobao-favorites-page],.ice-stark-loaded,.fav-main,#fav-list')||document.body;
  const controls=[],seen=new Set();
  const add=(e,action,extra={})=>{if(!e||!visible(e)||seen.has(path(e)))return;seen.add(path(e));const r=e.getBoundingClientRect();
    const row={action,label:text(e),elementPath:path(e),href:e.tagName==='A'?e.href:null,disabled:!!e.disabled||e.getAttribute('aria-disabled')==='true',
      inViewport:r.bottom>0&&r.right>0&&r.top<innerHeight&&r.left<innerWidth,...extra};
    row.signature=JSON.stringify([row.action,row.label,row.elementPath,row.href,row.productId,row.selected,row.fieldPath]);controls.push(row);return row;};
  for(const a of document.querySelectorAll('a[href]'))if(folderUrl(a.href)&&/^(收藏夹|我的收藏|宝贝收藏|收藏的宝贝|商品收藏)$/.test(text(a)))add(a,'open_taobao_favorites');
  if(product)for(const e of document.querySelectorAll('[data-favorite-toggle],#J_AddFavorite,button,[role="button"],[class*="RightButton--"]')){
    const label=text(e);if(!/^(收藏|收藏宝贝|收藏商品|已收藏|取消收藏)(?:\s*\d+[万+]*)?$/.test(label))continue;
    if(e.closest('[data-product-card],[class*="recommend"],[class*="Recommend"]'))continue;
    const pressed=e.getAttribute('aria-pressed');const selected=pressed==='true'?true:pressed==='false'?false:/^(已收藏|取消收藏)/.test(label)?true:/^(收藏|收藏宝贝|收藏商品)(?:\s*\d+[万+]*)?$/.test(label)?false:null;
    add(e,'set_taobao_favorite',{productId:product.productId,selected,stateEvidence:pressed!==null?'aria-pressed':'visible-action-label'});
  }
  const cards=[];
  if(isFavoritesPage){
    const byId=new Map();
    for(const a of favoriteRoot.querySelectorAll('a[href]')){
      const id=productUrl(a.href);if(!id||!visible(a)||a.closest('[data-recommendation],[class*="recommend"],[class*="Recommend"]'))continue;
      const container=a.closest('[data-favorite-item],[data-product-card],li,.fav-item,[class*="collectItem"],[class*="CollectItem"]')||a;
      const title=text(a)||a.querySelector('img')?.alt||text(container).slice(0,180);if(!title)continue;
      const row=add(a,'open_taobao_favorite',{...id,label:title});
      if(!row)continue;
      const previous=byId.get(id.productId);if(previous){if(title.length>previous.title.length)previous.title=title;continue;}
      const card={...id,title:title.slice(0,240),displayPrice:(text(container).match(/[¥￥]\s*[\d,.]+/)||[])[0]||null,signature:row.signature};byId.set(id.productId,card);cards.push(card);
    }
    for(const button of favoriteRoot.querySelectorAll('button,input[type="submit"],[role="button"]')){
      if(!/^(搜索|搜收藏|搜收藏夹)$/.test(text(button)||button.value||''))continue;
      const box=button.closest('form,[data-favorites-search],.fav-search,.search-form');if(!box||!favoriteRoot.contains(box)||box.closest('header,[role="banner"],#J_Search,.site-nav'))continue;
      const fields=[...box.querySelectorAll('input[name="q"],input[name="keyword"],input[type="search"],input[placeholder*="搜"]')].filter(e=>visible(e)&&!e.disabled&&!e.readOnly);
      if(fields.length===1)add(button,'favorites_search',{fieldPath:path(fields[0]),query:fields[0].value});
    }
  }
  const empty=isFavoritesPage&&[...document.querySelectorAll('[data-favorites-empty],.empty,[class*="empty"],[class*="Empty"]')].some(e=>visible(e)&&/暂无|没有|空空|未收藏/.test(text(e)));
  return {url:location.href,productId:product?.productId||null,isFavoritesPage,controls,cards,empty,
    scroll:{top:scrollY,height:document.documentElement.scrollHeight,viewport:innerHeight,atBottom:scrollY+innerHeight>=document.documentElement.scrollHeight-3},coverage:'loaded rendered DOM only; recommendations excluded; missing items may be unloaded'};
}
// HUOYAN_DOM_END
module.exports={readFavorites};
