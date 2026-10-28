// HUOYAN_DOM_BEGIN
function readShopPage() {
  const text=e=>(e?.innerText||e?.getAttribute('aria-label')||e?.title||'').replace(/\s+/g,' ').trim();
  const rendered=e=>{if(!e||e.closest('[hidden],[inert]'))return false;const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>1&&r.height>1&&s.display!=='none'&&s.visibility!=='hidden';};
  const path=e=>{const p=[];for(;e&&e.nodeType===1;e=e.parentElement){if(e===document.documentElement){p.unshift('html');break;}p.unshift(e.tagName.toLowerCase()+':nth-child('+([...e.parentElement.children].indexOf(e)+1)+')');}return p.join(' > ');};
  const visibility=e=>{const r=e.getBoundingClientRect();let l=Math.max(0,r.left),t=Math.max(0,r.top),b=Math.min(innerHeight,r.bottom),right=Math.min(innerWidth,r.right);for(let p=e.parentElement;p;p=p.parentElement){const s=getComputedStyle(p),q=p.getBoundingClientRect();if(/auto|scroll|hidden|clip/.test(s.overflowX)){l=Math.max(l,q.left);right=Math.min(right,q.right);}if(/auto|scroll|hidden|clip/.test(s.overflowY)){t=Math.max(t,q.top);b=Math.min(b,q.bottom);}}const inViewport=right>l&&b>t,hit=inViewport?document.elementFromPoint((l+right)/2,(t+b)/2):null;const disabled=!!e.disabled||e.getAttribute('aria-disabled')==='true';return {rendered:rendered(e),inViewport,actionable:inViewport&&!!hit&&(hit===e||e.contains(hit))&&!disabled,disabled,needsScroll:!inViewport};};
  const selected=e=>e.getAttribute('aria-selected')==='true'||e.getAttribute('aria-current')==='page'||e.getAttribute('aria-pressed')==='true'||/(?:^|\s)(?:active|selected|current)(?:--|\s|$)/i.test(e.className||'');
  const shopUrl=href=>{try{const u=new URL(href);if(u.protocol!=='https:'||u.username||u.password)return null;let key=null,shopId=null,source=null;
    const m=u.hostname.match(/^shop(\d+)\.(?:mall\.)?taobao\.com$/);if(m){shopId=m[1];key='taobao:shop:'+shopId;source='shop-host-id';}
    else if(/^[a-z0-9-]+\.tmall\.com$/.test(u.hostname)&&!['www','detail','login','list','pages','mall','chaoshi'].includes(u.hostname.split('.')[0])){key='tmall:host:'+u.hostname;source='shop-host';}
    else if(u.hostname==='store.taobao.com'&&/^\/(?:shop\/view_shop|search)\.htm$/.test(u.pathname)&&/^\d+$/.test(u.searchParams.get('shop_id')||'')){shopId=u.searchParams.get('shop_id');key='taobao:shop:'+shopId;source='shop-link-id';}
    return key?{key,shopId,sellerId:null,url:u.href,source,verification:'page-evidence'}:null;
  }catch{}return null;};
  const local=shopUrl(location.href),nameNode=[...document.querySelectorAll('[data-shop-name],.shop-name,.slogo-shopname,[class*="shopName--"],[class*="ShopName--"]')].find(rendered);
  const identity=local?{...local,name:text(nameNode)||null}:null;
  if(identity){const sellers=[...document.querySelectorAll('[data-seller-id]')].filter(rendered).map(e=>e.getAttribute('data-seller-id')).filter(x=>/^\d+$/.test(x));if(new Set(sellers).size===1){identity.sellerId=sellers[0];identity.sellerIdSource='visible-data-seller-id';}}
  const controls=[],seen=new Set(),searchPairs=[],shops=[];
  const add=(e,action,extra={})=>{if(!rendered(e)||seen.has(path(e)))return;const label=text(e)||e.value||'';if(!label||label.length>240||/购物车|加购|收藏|购买|结算|登录|验证|投诉|客服|联系|领券|领取|订阅|关注|设置/.test(label))return;
    seen.add(path(e));const row={elementPath:path(e),action,label,href:e.tagName==='A'?e.href:null,tag:e.tagName,selected:selected(e),expanded:e.getAttribute('aria-expanded'),region:extra.region||'shop',...visibility(e),...extra};row.signature=JSON.stringify([action,label,row.href,row.elementPath,row.region]);controls.push(row);return row;};
  for(const a of document.querySelectorAll('a[href]')){const id=shopUrl(a.href);if(!id||!rendered(a))continue;const scope=a.closest('[data-shop-card],.shop-card,[class*="shopCard"],[class*="ShopCard"],[class*="shopName"],[class*="ShopName"],.shop-name,.slogo-shopname');
    if(identity?.key===id.key&&a.closest('.shop-nav,.shop-navigation,[class*="shopNav"],[class*="ShopNav"]'))continue;
    if(!scope&&!/^(进入店铺|进店逛逛|进店|店铺首页)$/.test(text(a)))continue;
    const row=add(a,'open_shop',{shopIdentity:{...id,name:text(scope?.querySelector('[data-shop-name]'))||text(a)||null},region:'shop-entry'});if(row)shops.push({identity:row.shopIdentity,elementPath:row.elementPath,label:row.label});}
  for(const e of document.querySelectorAll('button,input[type="submit"],[role="button"]')){const label=text(e)||e.value;if(!/^(搜索|搜 索|搜本店|搜全站)$/.test(label)||!rendered(e))continue;
    const container=e.closest('form,[data-shop-search],[data-global-search],.shop-search,.shop-search-box,.search-shop,.shop-search-form');let scope=null;
    if(label==='搜本店'||container?.matches('[data-shop-search],.shop-search,.shop-search-box,.search-shop,.shop-search-form')||container?.getAttribute('data-search-scope')==='shop')scope='shop';
    else if(label==='搜全站'||container?.matches('[data-global-search]')||container?.getAttribute('data-search-scope')==='global')scope='global';
    else if(identity&&container){const action=container.getAttribute('action');let actionIdentity=null;try{actionIdentity=shopUrl(new URL(action||location.href,location.href).href);}catch{}if(actionIdentity?.key===identity.key)scope='shop';else if(action)scope='global';}
    else if(!identity&&container)scope='global';
    const fields=container?[...container.querySelectorAll('input[name="q"],input[name="keyword"],input[name="keywords"],input[type="search"],input[placeholder*="搜索"],input[placeholder*="搜宝贝"]')].filter(x=>rendered(x)&&!x.disabled&&!x.readOnly):[];
    searchPairs.push({buttonPath:path(e),fieldPath:fields.length===1?path(fields[0]):null,scope,label,query:fields.length===1?fields[0].value:null,pairing:fields.length===1?'same-container':'ambiguous-or-missing'});
  }
  if(!identity)for(const e of document.querySelectorAll('[data-search-target],[role="tab"],button,[role="option"]'))if(['店铺','宝贝','商品'].includes(text(e))&&!e.closest('[data-product-card]'))add(e,e.getAttribute('aria-haspopup')&&e.getAttribute('aria-haspopup')!=='false'?'search_target_menu':'search_target',{target:text(e)==='店铺'?'shops':'products',region:'search-target'});
  if(identity){
    for(const e of document.querySelectorAll('[data-shop-section],.shop-nav a,.shop-navigation a,[class*="shopNav"] a,[class*="ShopNav"] a,[class*="shopTabs"] [role="tab"]'))add(e,'shop_section',{region:'shop-navigation'});
    for(const e of document.querySelectorAll('[data-shop-category],.shop-category a,.shop-category button,.shop-category [role="button"],.cat-tree a,.cat-tree summary,.category-list a'))add(e,'shop_category',{region:'shop-category'});
  }
  const selectedSections=controls.filter(c=>c.action==='shop_section'&&c.selected).map(c=>c.label),selectedCategories=controls.filter(c=>c.action==='shop_category'&&c.selected).map(c=>c.label);
  const shopPairs=searchPairs.filter(p=>p.scope==='shop'&&p.fieldPath),query=shopPairs.length===1?shopPairs[0].query:null;
  const url=new URL(location.href),applied=url.searchParams.get('keyword')??url.searchParams.get('keywords')??url.searchParams.get('q');
  const marker=[...document.querySelectorAll('[data-shop-query],[data-search-query],.search-result-keyword,.search-keyword')].find(rendered);
  const queryEvidence=marker?{value:marker.getAttribute('data-shop-query')??marker.getAttribute('data-search-query')??text(marker),source:'visible-result-query'}:applied!==null?{value:applied,source:'current-url-query'}:null;
  let stage='unknown';if(identity){if(queryEvidence)stage='search-results';else if(selectedCategories.length)stage='category';else if(selectedSections.some(x=>/全部/.test(x)))stage='all-products';else if(/^\/(?:index.htm[l]?)?$/.test(location.pathname))stage='home';}
  const productRegions=[...document.querySelectorAll('a[href*="item.htm"]')].filter(rendered).map(a=>({elementPath:path(a),href:a.href,region:a.closest('[data-recommendation],.recommend,.recommendations,[class*="recommend"],[class*="Recommend"]')?'recommendation':a.closest('[data-shop-products],.shop-products,.shop-search-result,.search-result,.item-list,.J_TItems')?'shop-products':'unverified'}));
  const controlVisibility=[...document.querySelectorAll('a[href],button,input,[role="button"],[role="tab"],[role="menuitem"],[role="option"],[role="checkbox"],[role="radio"],summary,label,[data-filter-option]')].filter(rendered).map(e=>({elementPath:path(e),...visibility(e)}));
  return {identity,isShopPage:!!identity,stage,controls,shops,searchPairs,query,queryEvidence,selectedSections,selectedCategories,productRegions,controlVisibility,iframeCount:document.querySelectorAll('iframe').length,scroll:{x:scrollX,y:scrollY},searchTarget:controls.find(c=>c.action==='search_target'&&c.selected)?.target||null};
}
// HUOYAN_DOM_END
module.exports={readShopPage};
