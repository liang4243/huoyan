// HUOYAN_DOM_BEGIN
function readResearchPage() {
  const visible = e => { const r=e.getBoundingClientRect(),s=getComputedStyle(e); return r.width>1&&r.height>1&&s.visibility!=='hidden'&&s.display!=='none'; };
  const text = e => (e.innerText||e.getAttribute('aria-label')||e.title||(e.matches('input[type="submit"]')?e.value:'')||(e.labels?[...e.labels].map(l=>l.innerText).join(' '):'')||'').replace(/\s+/g,' ').trim();
  const selected = e => e.getAttribute('aria-selected')==='true'||e.getAttribute('aria-checked')==='true'||e.getAttribute('aria-pressed')==='true'||e.checked===true||[...e.classList].some(c=>/^(?:(?:is)?(?:selected|active|current|checked)|tb-selected|filterItemActive)(?:--|$)/i.test(c))||(e.matches('[class*="priceTag--"]')&&e.style.fontWeight==='bold'&&!!e.style.backgroundColor);
  const disabled = e => !!e.disabled||e.getAttribute('aria-disabled')==='true'||getComputedStyle(e).cursor==='not-allowed'||[...e.classList].some(c=>/^(?:(?:is)?disabled|tb-out-of-stock)(?:--|$)/i.test(c));
  const filterScope='[data-filter-group],[data-filter-panel],[class*="filterPanel"],[class*="FilterPanel"],[class*="filterItem--"],[class*="FilterItem"],[class*="filterContent"],[class*="FilterContent"],[class*="filterDropdown"],[class*="FilterDropdown"],[class*="filterBoxWrapper"],[class*="priceRange"],[class*="sectionPriceSelecter"]';
  const selector='a[href],button,input[type="submit"],[role="button"],[role="tab"],[role="menuitem"],[role="option"],[role="checkbox"],[role="radio"],summary,input[type="checkbox"],label,#filterMoreButton_id,[data-filter-option],[class*="priceTag--"],[class*="filterItem--"],[class*="filterBoxWrapper"] [class*="reset"],[class*="filterBoxWrapper"] [class*="Reset"],[class*="filterBoxWrapper"] [class*="closeIcon"],[class*="sectionPriceSelecter"] [class*="confirmButton"],[class*="sectionPriceSelecter"] [class*="resetButton"],[class*="tabTitleItem--"],[class*="switchTabsItem--"],[class*="thumbnailOtherPic--"]';
  const nodes=[...document.querySelectorAll(selector)];
  const controls=[];
  for(const [index,e] of nodes.entries()) {
    if(!visible(e))continue;
    const label=e.matches('[class*="filterBoxWrapper"] [class*="closeIcon"]')?'关闭筛选':text(e), href=e.tagName==='A'?e.href:null;
    if(!label||label.length>240||/购物车|加购|收藏|购买|(?<!人)付款|结算|登录|注册|验证|删除|投诉|联系|客服|领取|领券|订阅|个性化|设置/.test(label))continue;
    let action=null;
    const filter=e.closest(filterScope);
    if(/^(搜索|搜 索|搜全站|搜本店)$/.test(label))action='search';
    else if(/^(综合|销量|价格)$/.test(label)||/^(新品|上新)$/.test(label)&&(e.getAttribute('role')==='tab'||e.closest('[data-sort],[data-sort-bar],.sort-bar,.sortbar,.sort-items')))action='sort';
    else if(/^(价格)?(从低到高|从高到低|升序|降序)$/.test(label))action='sort_direction';
    else if(/^(筛选|更多筛选)$/.test(label))action='filter_panel';
    else if(label==='区间'&&e.getAttribute('role')==='tab')action='price_panel';
    else if(label==='关闭筛选')action='close_filter_panel';
    else if(e.tagName==='BUTTON'&&/^第\d+页，共\d+页$/.test(e.getAttribute('aria-label')||''))action='page_number';
    else if(e.matches('.next-pagination-jump-go,[data-page-jump]'))action='page_jump';
    else if(/^(下一页|下页)(\s*>|\s*，.*)?$/.test(label)||/^下一页/.test(e.getAttribute('aria-label')||''))action='next_page';
    else if(/^(上一页|上页)$/.test(label)||/^上一页/.test(e.getAttribute('aria-label')||''))action='previous_page';
    else if(filter&&/^(确定|确认|应用|完成)$/.test(label))action='apply_filters';
    else if(filter&&/^(清空|清除|重置|清空筛选|重置筛选)$/.test(label))action='clear_filters';
    else if(filter&&label.length<=60&&!e.closest('[data-product-card],[class*="doubleCardWrapper"],[class*="skuItem"]'))action='filter_option';
    else if(/^(商品详情|宝贝详情|图文详情|图集|详情|参数信息|参数|规格参数|商品参数|用户评价|宝贝评价|评价|追评|问大家)(?:\s*[（(]?\d+[万+]*[）)]?)?$/.test(label)&&(!href||e.getAttribute('role')==='tab'||href.includes('#')))action='section';
    else if(href) {
      try {const u=new URL(href);if(u.protocol==='https:'&&!u.username&&!u.password&&/(^|\.)(taobao|tmall)\.com$/.test(u.hostname)) {
        if(['item.taobao.com','detail.tmall.com'].includes(u.hostname)&&u.pathname==='/item.htm'&&/^\d+$/.test(u.searchParams.get('id')||''))action='open_product';
        else if(u.hostname==='www.taobao.com'&&/^\/(index.htm[l]?)?$/.test(u.pathname))action='home';
        else if(/^(进入店铺|进店逛逛|进店|店铺首页)$/.test(label))action='open_shop';
      }}catch{}
    }
    const suggest=e.closest('[role="listbox"],[data-search-suggestions]');
    if(!action&&suggest&&e.getAttribute('role')==='option'&&label.length<=80)action='search_suggestion';
    const group=filter?(filter.closest('[data-filter-group],[class*="filterCPVblock"]')?.querySelector('[data-filter-label],legend,[class*="title"],[class*="Title"]')?.innerText||filter.getAttribute('aria-label')||'').trim().slice(0,60):null;
    const region=e.closest('[class*="filterBoxWrapper"],[data-filter-panel]')?'filter-panel':e.closest('[data-filter-group]')?'filter-group':'page';
    let searchScope=null;
    if(action==='search'){
      if(label==='搜本店')searchScope='shop';else if(label==='搜全站')searchScope='global';
      else {const form=e.closest('form');if(form?.querySelector('input[name="q"]'))searchScope='global';else if(/shop/.test(location.hostname)&&form?.querySelector('input[name="keyword"],input[name="keywords"]'))searchScope='shop';}
    }
    if(action)controls.push({index,action,label,href,tag:e.tagName,selected:selected(e),disabled:disabled(e),expanded:e.getAttribute('aria-expanded'),group,region,...(action==='search'?{searchScope}:{}),...(action==='page_number'?{pageNumber:Number((e.getAttribute('aria-label').match(/^第(\d+)页/)||[])[1])}:{}),...(e.matches('[class*="priceTag--"]')&&selected(e)?{selectionEvidence:'inline-bold-and-background'}:{}),signature:JSON.stringify([e.tagName,label,href,group,region])});
  }
  const inputs=[...document.querySelectorAll('input')], fields=[];
  for(const [index,e] of inputs.entries()) {
    if(!visible(e)||disabled(e)||e.readOnly||/password|hidden|file/.test(e.type))continue;
    const label=[e.getAttribute('aria-label'),e.placeholder,e.name].filter(Boolean).join(' ');
    let kind=null;
    if(/跳转到第几页/.test(label))kind='page_number';
    else if(/^(q|keyword|keywords)$/.test(e.name)||e.type==='search')kind='search';
    else if(e.closest(filterScope)||/价格|最低|最高|最低价|最高价|price/i.test(label)) {
      if(/最低|起始|最小|低价|min|start/i.test(label))kind='price_min';
      if(/最高|结束|最大|高价|max|end/i.test(label))kind='price_max';
    }
    if(kind)fields.push({index,kind,label,value:e.value,signature:JSON.stringify([e.type,e.name,e.placeholder,e.getAttribute('aria-label')])});
  }
  const products=[],seen=new Set();
  for(const a of document.querySelectorAll('a[href]')) {
    if(!visible(a))continue;
    let u;try{u=new URL(a.href);}catch{continue;}
    if(!['item.taobao.com','detail.tmall.com'].includes(u.hostname)||u.pathname!=='/item.htm'||!/^\d+$/.test(u.searchParams.get('id')||''))continue;
    const id=u.searchParams.get('id');if(seen.has(id))continue;seen.add(id);
    const card=a.closest('[data-product-card],[class*="doubleCardWrapper"],[class*="cardItem"],li')||a;
    const content=text(card).slice(0,1400),image=card.querySelector('img');
    const match=content.replace(/(\d)\s*\.\s*(\d)/g,'$1.$2').match(/[¥￥]\s*(\d+(?:\.\d+)?(?:\s*[-~至]\s*\d+(?:\.\d+)?)?)/);
    const priceNode=card.querySelector('[data-price],[class*="priceInt"],[class*="PriceInt"],[class*="price--"]');
    products.push({productId:id,url:`https://${u.hostname}/item.htm?id=${id}`,title:(a.title||image?.alt||card.querySelector('[data-product-title],[class*="title--"],[class*="Title--"],[class*="titleText"],h3')?.innerText||content).slice(0,220),displayPrice:match?.[1]||priceNode?.innerText||null,salesText:(content.match(/\S*(?:人付款|人收货|人购买|已售|销量)\S*/)||[])[0]||null,shop:card.querySelector('[data-shop],[class*="shopName"],[class*="ShopName"]')?.innerText||null,adLabel:/广告/.test(content)?'广告':null,evidence:content});
    if(products.length>=100)break;
  }
  const nonPriceSelected=controls.some(c=>c.action==='sort'&&c.selected&&['综合','销量','新品','上新'].includes(c.label));
  const sort=controls.filter(c=>['sort','sort_direction'].includes(c.action)&&c.selected&&(!nonPriceSelected||c.action==='sort'));
  // Taobao's price items use inline bold/background instead of ARIA. Preserve explicit evidence,
  // including whether that menu is currently visible; never infer from the price-tab hover color.
  if(!nonPriceSelected)for(const e of document.querySelectorAll('[class*="priceTag--"]'))if(selected(e)&&!sort.some(c=>c.label===text(e)))sort.push({label:text(e),selected:true,selectionEvidence:'inline-bold-and-background',menuVisible:visible(e)});
  const sortText=sort.map(c=>c.label).join(' ');
  let direction=/从低到高|升序/.test(sortText)?'asc':/从高到低|降序/.test(sortText)?'desc':null;
  // Only explicit textual/ARIA evidence establishes direction; icon appearance is insufficient.
  if(!direction)for(const c of sort){const e=nodes[c.index];if(!e)continue;const s=[e.getAttribute('aria-label'),e.getAttribute('data-direction'),e.getAttribute('data-sort')].filter(Boolean).join(' ');if(/从低到高|升序|\basc\b/i.test(s))direction='asc';if(/从高到低|降序|\bdesc\b/i.test(s))direction='desc';}
  const pagination=[...document.querySelectorAll('[aria-current="page"],[data-current-page],button[aria-label*="当前第"],[class*="pagination"] [class*="current"]')].filter(visible).map(e=>e.getAttribute('aria-label')||e.getAttribute('data-current-page')||text(e));
  const pageEvidence=pagination.find(x=>/当前第\d+页|^第\d+页，共\d+页$/.test(x))||pagination.find(x=>/^\d+$/.test(x));
  const currentPage=pageEvidence?Number((pageEvidence.match(/(?:当前)?第(\d+)页/)||[])[1]||pageEvidence):null;
  const totalEvidence=pagination.find(x=>/共\d+页/.test(x));
  const totalPages=totalEvidence?Number(totalEvidence.match(/共(\d+)页/)[1]):null;
  const imageSelector='[data-product-thumbnail],#J_UlThumb li,[class*="thumbnail"] button,[class*="Thumbnail"] button,[class*="thumbnail"] img,[class*="Thumbnail"] img,img[class*="thumbnail"],[class*="PicGallery"] li,[class*="picGallery"] li';
  const images=[...document.querySelectorAll(imageSelector)].map((e,index)=>({index,visible:visible(e),label:text(e)||e.querySelector('img')?.alt||e.alt||`图片${index+1}`,src:(e.tagName==='IMG'?e:e.querySelector('img'))?.currentSrc||null,selected:selected(e),disabled:disabled(e)})).filter(x=>x.visible&&!x.disabled).slice(0,30);
  const currentImages=[...document.querySelectorAll('[data-product-main-image],#J_ImgBooth,.tb-booth img,[class*="mainPic"] img,img[class*="mainPic--"],[class*="MainPic"] img')].filter(visible).map(e=>e.currentSrc||e.src).slice(0,6);
  const sectionNodes='[data-product-description],#J_DivItemDesc,#description,[data-product-parameters],[data-product-reviews],[data-product-questions],[role="tabpanel"],[class*="description"],[class*="Description"],[class*="comment"],[class*="Comment"],[class*="parameter"],[class*="Parameter"],[class*="paramsInfo"]';
  const sections=[...document.querySelectorAll(sectionNodes)].filter(visible).map(e=>({label:e.getAttribute('aria-label')||e.id||e.getAttribute('role')||'商品内容',text:text(e).slice(0,10000)})).filter(x=>x.text).slice(0,12);
  const query=fields.find(f=>f.kind==='search')?.value||null;
  let appliedPriceRange=null;
  const rangeNode=document.querySelector('[data-applied-price-min],[data-applied-price-max]');
  if(rangeNode&&visible(rangeNode))appliedPriceRange={min:rangeNode.getAttribute('data-applied-price-min'),max:rangeNode.getAttribute('data-applied-price-max'),evidence:'visible-applied-range'};
  let pageType='other';
  if(/^(item.taobao.com|detail.tmall.com)$/.test(location.hostname)&&location.pathname==='/item.htm')pageType='product';
  else if(/shop/.test(location.hostname))pageType='shop';
  else if(location.hostname==='s.taobao.com'||products.length>0&&query)pageType='search';
  else if(location.hostname==='www.taobao.com')pageType='home';
  return {url:location.href,title:document.title,pageType,query,searchScope:pageType==='shop'?'shop':'global',sort:{field:sortText.includes('价格')||direction?'price':sortText.includes('销量')?'sales':/新品|上新/.test(sortText)?'newest':sortText.includes('综合')?'comprehensive':null,direction,evidence:sort.map(c=>({label:c.label,selected:c.selected,...(c.selectionEvidence?{selectionEvidence:c.selectionEvidence}:{} )}))},pagination,currentPage,totalPages,filterPanelVisible:[...document.querySelectorAll('[data-filter-panel],[class*="filterBoxWrapper"]')].some(visible),appliedPriceRange,filters:controls.filter(c=>c.action==='filter_option'&&c.selected).map(c=>({label:c.label,group:c.group})),fields,controls,products,images,currentImages,sections,noResults:/没有找到相关|暂无相关商品|没有搜索到|没有符合条件/.test(document.body?.innerText||''),selector,imageSelector};
}
// HUOYAN_DOM_END
module.exports={readResearchPage};
