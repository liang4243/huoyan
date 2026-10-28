// HUOYAN_DOM_BEGIN
function readDetailPage() {
  const norm = s => String(s || '').replace(/\s+/g, ' ').trim();
  const contentId = s => {let h=2166136261;for(const ch of s){h=Math.imul(h^ch.charCodeAt(0),16777619);}return (h>>>0).toString(16);};
  const text = e => norm(e?.innerText || e?.getAttribute('aria-label') || e?.title);
  const rendered = e => { if (!e) return false; const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>1&&r.height>1&&s.display!=='none'&&s.visibility!=='hidden'&&!e.closest('[hidden],[inert]'); };
  const selected = e => e.getAttribute('aria-selected')==='true'||e.getAttribute('aria-checked')==='true'||e.getAttribute('aria-pressed')==='true'||[...e.classList].some(c=>/^(?:(?:is)?(?:selected|active|current|checked)|tb-selected)(?:--|$)/i.test(c)||/^switchTabsItemSelect--/.test(c));
  const disabled = e => Boolean(e.disabled||e.getAttribute('aria-disabled')==='true'||getComputedStyle(e).cursor==='not-allowed'||[...e.classList].some(c=>/^(?:(?:is)?disabled|tb-out-of-stock)(?:--|$)/i.test(c)));
  const path = e => {const a=[];for(let n=e;n&&n!==document.documentElement;n=n.parentElement){if(!n.parentElement)return null;a.unshift(n.tagName.toLowerCase()+':nth-child('+([...n.parentElement.children].indexOf(n)+1)+')');}return 'html > '+a.join(' > ');};
  const all = (selector,root=document) => [...root.querySelectorAll(selector)].filter(rendered);
  const geometry = e => {
    let r=e.getBoundingClientRect(),left=Math.max(0,r.left),top=Math.max(0,r.top),right=Math.min(innerWidth,r.right),bottom=Math.min(innerHeight,r.bottom);
    for(let p=e.parentElement;p;p=p.parentElement){const s=getComputedStyle(p),a=p.getBoundingClientRect();if(/hidden|clip|auto|scroll/.test(s.overflowX)){left=Math.max(left,a.left);right=Math.min(right,a.right);}if(/hidden|clip|auto|scroll/.test(s.overflowY)){top=Math.max(top,a.top);bottom=Math.min(bottom,a.bottom);}}
    const inViewport=right>left&&bottom>top;
    const points=inViewport?[[.5,.5],[.25,.5],[.75,.5]].map(([x,y])=>document.elementFromPoint(left+(right-left)*x,top+(bottom-top)*y)):[];
    const hit=points.some(hit=>hit&&(hit===e||e.contains(hit)));
    return {rendered:true,inViewport,actionable:inViewport&&hit&&!disabled(e),needsScroll:!inViewport,blockedByOverlay:inViewport&&!hit};
  };
  const roots=all('[data-detail-panel],[role="dialog"],[class*="Drawer--"],[class*="drawer--"],[class*="moreGuaranteeListWrap--"]');
  const panels=[];
  for(const e of roots){
    let kind=e.getAttribute('data-detail-panel');
    if(e.matches('[class*="moreGuaranteeListWrap--"]'))kind='services';
    if(!kind){if(e.querySelector('[class*="Comments--"],[data-product-reviews]'))kind='reviews';else if(e.matches('[class*="askAnswerInfoDrawer--"]')||e.querySelector('[data-question],[class*="moreAnswerBtn--"],[class*="AskAnswersWrap--"]'))kind='questions';else if(e.querySelector('[data-product-parameters],[class*="paramsInfo"]'))kind='parameters';else if(e.querySelector('[data-service-text],[class*="guaranteeText--"]'))kind='services';else if(e.querySelector('[data-product-main-image]'))kind='image';}
    if(!['reviews','questions','parameters','services','image'].includes(kind))continue;
    if(panels.some(p=>p.node.contains(e)))continue;
    const toggle=e.matches('[class*="moreGuaranteeListWrap--"]')?e.parentElement.querySelector('[class*="GuaranteeInfo--"] [class*="triggerWrap--"]'):null;
    panels.push({node:e,panelId:'panel-'+panels.length,kind,elementPath:path(e),dismissal:toggle?'trigger-toggle':'close-button',dismissPath:toggle?path(toggle):null});
  }
  const panelFor=e=>panels.find(p=>p.node.contains(e));
  const controls=[],seen=new Set();
  const add=(e,action,region,extra={})=>{
    if(!rendered(e)||seen.has(e))return null;
    const label=extra.label||text(e);
    if(!label||label.length>240||/加购|购物车|购买|付款|结算|收藏|领券|领取|登录|注册|验证|客服|发送|订阅|投诉|举报/.test(label))return null;
    seen.add(e);const p=panelFor(e);
    const row={elementPath:path(e),action,label,region,selected:selected(e),disabled:disabled(e),...geometry(e),panelId:p?.panelId||null,...extra};
    row.signature=JSON.stringify([action,region,label,row.elementPath,row.panelId]);controls.push(row);return row;
  };
  for(const e of all('[data-detail-section],[class*="tabTitleItem--"],[class*="switchTabsItem--"],[class*="thumbnailOtherPic--"],[role="tab"]')){
    if(!/^(用户评价|宝贝评价|评价|参数信息|参数|规格参数|商品参数|图文详情|商品详情|宝贝详情|图集|问大家)$/.test(text(e)))continue;
    const region=e.getAttribute('data-detail-region')||(/switchTabsItem|thumbnailOtherPic/.test(e.className)?'gallery':'body');
    add(e,'section',region);
  }
  for(const e of all('[data-open-reviews],[class*="Comments--"] [class*="ShowButton--"]'))if(/查看全部评价|全部评价/.test(text(e)))add(e,'open_reviews','body');
  for(const e of all('[data-open-shop-reputation],[class*="shopHeader--"] img[class*="creditLevelIconImg--"]'))if(!e.closest('[data-recommendation],[class*="recommend"],[class*="Recommend"]'))add(e,'shop_reputation','shop-header',{label:'悬浮查看店铺评分与信誉',interaction:'hover'});
  for(const p of panels){
    for(const e of all('[data-close-detail],[aria-label="关闭"],button,[class*="closeWrap--"]',p.node)){
      if(e.matches('[data-close-detail],[class*="closeWrap--"]')||/^(关闭|×)$/.test(text(e)))add(e,'close_detail_panel',p.kind+'-panel',{label:'关闭'+p.kind});
    }
    if(p.kind==='reviews'){
      for(const e of all('[data-review-filter],[class*="imprItem--"],[class*="sortItem--"],[role="option"],[role="checkbox"],[role="radio"]',p.node))add(e,'review_filter','reviews-panel',{group:e.getAttribute('data-review-group')||(/sortItem/.test(e.className)?'sort':'filter')});
      for(const e of all('[data-review-menu],[class*="sortByText--"],[class*="shapeFliterWrap--"]',p.node))add(e,'review_menu','reviews-panel');
    }
  }
  const groupNodes=all('#J_isku .J_TSaleProp,[class*="skuItem"],[class*="SkuItem"]').filter(e=>!e.parentElement?.closest('#J_isku .J_TSaleProp,[class*="skuItem"],[class*="SkuItem"]'));
  const skuGroups=groupNodes.map((e,groupIndex)=>{
    const candidates=all('li,[class*="valueItem"],[class*="ValueItem"],[role="radio"],a',e);
    const opts=candidates.filter(n=>!candidates.some(p=>p!==n&&p.contains(n)));
    const label=text(e.querySelector('[class*="name"],[class*="label"],.tb-metatit'))||'规格'+(groupIndex+1);
    return {groupIndex,label,options:opts.map(n=>add(n,'select_sku','sku',{groupIndex,groupLabel:label})).filter(Boolean)};
  }).filter(g=>g.options.length);
  const parameterRoots=all('[data-product-parameters],[class*="paramsInfo"]');
  const parameters=[];
  for(const root of parameterRoots.filter(e=>!parameterRoots.some(p=>p!==e&&p.contains(e)))){
    const rows=all('[data-parameter-row],tr,dl,[class*="paramsItem"],[class*="paramItem"],[class*="infoItem"],[class*="emphasisParamsInfoItem--"],[class*="generalParamsInfoItem--"]',root);
    for(const row of rows){
      const emphasis=row.matches('[class*="emphasisParamsInfoItem--"]');
      const keyNode=row.querySelector(emphasis?'[class*="emphasisParamsInfoItemSubTitle--"]':'[data-parameter-key],dt,th,[class*="label"],[class*="Label"],[class*="name"],[class*="Name"],[class*="generalParamsInfoItemTitle--"]');
      const valueNode=row.querySelector(emphasis?'[class*="emphasisParamsInfoItemTitle--"]':'[data-parameter-value],dd,td,[class*="value"],[class*="Value"],[class*="generalParamsInfoItemSubTitle--"]');
      const key=text(keyNode),value=text(valueNode);if(key&&value)parameters.push({key,value,source:'product-parameters',scope:'product-general'});
    }
  }
  const parameterText=[...new Set(parameterRoots.map(text))].filter(Boolean).map(t=>t.slice(0,6000)).slice(0,4);
  const reviews=[];
  const reviewPanels=panels.filter(p=>p.kind==='reviews');
  const reviewNodes=all('[data-review],[class*="Comment--"]').filter(e=>!reviewPanels.length||reviewPanels.some(p=>p.node.contains(e)));
  for(const e of reviewNodes.filter(e=>!reviewNodes.some(p=>p!==e&&p.contains(e)))){
    const body=e.querySelector('[data-review-text],[class*="content--"]');
    if(!body||!rendered(body)||!text(body))continue;
    const meta=text(e.querySelector('[data-review-meta],[class*="meta--"]'));
    const images=all('[data-review-image], [class*="album--"] img',e).map(n=>({src:n.currentSrc||n.src,width:n.naturalWidth,height:n.naturalHeight})).filter(i=>i.src);
    const followUp=text(e.querySelector('[data-review-followup],[class*="appendContent"]'));
    reviews.push({reviewId:'review-'+contentId(text(body)+meta),text:text(body).slice(0,3000),date:(meta.match(/20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}日?/)||[])[0]||null,sku:text(e.querySelector('[data-review-sku],[class*="sku--"]'))||null,followUp:followUp||null,images,source:panelFor(e)?'reviews-panel':'product-preview'});
  }
  const questions=[];
  const questionPanels=panels.filter(p=>p.kind==='questions');
  const qRoots=all('[data-question],[class*="questionItem--"],[class*="QuestionItem--"],[class*="askItem--"],[class*="askAnswerItem--"],[class*="qaItem--"]').filter(e=>!questionPanels.length||questionPanels.some(p=>p.node.contains(e)));
  for(const [i,e] of qRoots.entries()){
    const question=text(e.querySelector('[data-question-text],[class*="questionText"],[class*="title--"],[class*="questionRow--"],[class*="questionTitle--"]')).replace(/^问\s+/,'');
    if(!question)continue;
    const q={questionId:'question-'+contentId(question),question,answers:all('[data-answer-text],[class*="answerText"],[class*="answer--"],[class*="answerContent--"]',e).map(text).filter(Boolean).slice(0,30)};
    const more=all('[data-more-answers],[class*="moreAnswerBtn--"]',e);for(const n of more)add(n,'expand_question_answers','questions',{questionId:q.questionId});
    questions.push(q);
  }
  // An unclassified "more answers" is exposed for discovery, never attached to a guessed question.
  for(const e of all('[class*="moreAnswerBtn--"]'))add(e,'expand_question_answers','questions',{questionId:null});
  for(const e of all('[data-open-services],[class*="triggerWrap--"]'))if(/退货|运费险|退款|保障/.test(text(e)))add(e,'open_services','services');
  const services=[...new Set(all('[data-service-text],[class*="guaranteeText--"],[class*="GuaranteeItem--"]').map(text))].filter(Boolean).slice(0,30);
  // Do not return the destination or read address-editing controls.
  const delivery=all('[data-delivery-summary],[class*="deliveryAddrWrap--"]').map(e=>({origin:/至/.test(text(e))?text(e).split(/\s*至\s*/)[0].slice(0,40):null,destination:'redacted',source:'visible-delivery-summary'})).slice(0,3);
  const quantity=all('#J_IptAmount,input[class*="countValue"],input[name="quantity"]');
  for(const e of quantity)add(e,'set_quantity','quantity',{label:'数量',value:e.value,min:e.min||null,max:e.max||null});
  const imageNodes=all('[data-product-thumbnail],#J_UlThumb li,[class*="thumbnail"] img,[class*="Thumbnail"] img,[class*="mainPic"] img,img[class*="mainPic--"],[data-product-main-image],#J_ImgBooth,[data-product-image],#description img,#J_DivItemDesc img,.desc-root img,.descV8-container img,[data-review-image],[class*="album--"] img');
  const images=[];
  for(const e of imageNodes){
    const img=e.tagName==='IMG'?e:e.querySelector('img');if(!img)continue;
    const source=e.closest('[data-review],[class*="Comment--"]')?'review':e.closest('#description,#J_DivItemDesc,[data-product-description],.desc-root,.descV8-container')?'description':'gallery';
    const row=add(e,'gallery_image',source,{label:img.alt||'图片'+(images.length+1),src:img.currentSrc||img.src||null,width:img.naturalWidth,height:img.naturalHeight,skuAssociation:'unverified'});
    if(row)images.push(row);
  }
  for(const p of panels.filter(p=>p.kind==='image'))for(const e of all('[data-image-next],[data-image-previous],[aria-label="下一张"],[aria-label="上一张"]',p.node))add(e,'image_step','image-panel');
  const containers=[];
  const addContainer=(e,region)=>{if(!rendered(e)||containers.some(c=>c.elementPath===path(e)))return;const s=getComputedStyle(e);if(!/auto|scroll/.test(s.overflowY)&&!e.matches('[data-detail-scroll]'))return;containers.push({containerId:'container-'+containers.length,region,elementPath:path(e),top:e.scrollTop,height:e.scrollHeight,viewport:e.clientHeight,atBottom:e.scrollTop+e.clientHeight>=e.scrollHeight-2});};
  for(const p of panels)for(const e of all('[data-detail-scroll],[class*="comments--"],div',p.node))addContainer(e,p.kind+'-panel');
  containers.push({containerId:'document',region:'body',elementPath:null,top:scrollY,height:document.documentElement.scrollHeight,viewport:innerHeight,atBottom:scrollY+innerHeight>=document.documentElement.scrollHeight-2});
  const descriptionRoots=all('[data-product-description],#description,#J_DivItemDesc,.desc-root,.descV8-container');
  const descriptions=descriptionRoots.filter(e=>!descriptionRoots.some(p=>p!==e&&p.contains(e))).map(e=>text(e).slice(0,6000)).filter(Boolean).slice(0,3);
  const reviewSort=panels.filter(p=>p.kind==='reviews').flatMap(p=>all('[class*="sortByText--"]',p.node).map(e=>({label:text(e),evidence:'visible-sort-label'})));
  return {controls,skuGroups,parameters,parameterText,reviews:reviews.slice(0,100),reviewSort,questions,services,delivery,descriptions,images,panels:panels.map(({node,...p})=>p),containers,unverified:['final checkout price','coupon eligibility','server inventory','unloaded content','cross-origin frames'],iframeCount:document.querySelectorAll('iframe').length};
}
// HUOYAN_DOM_END
module.exports = { readDetailPage };
