// HUOYAN_DOM_BEGIN
function readCommerceEvidence(options = {}) {
  const norm=s=>String(s||'').replace(/\s+/g,' ').trim();
  const scrub=s=>norm(s).replace(/1[3-9]\d{9}/g,'[phone-redacted]');
  const privateSelector='script,style,noscript,[hidden],[inert],[data-private],[data-recipient],[data-address],[data-delivery-destination],[data-delivery-summary],[class*="deliveryAddrWrap"],[class*="address"],[class*="Address"],[class*="recipient"],[class*="userInfo"],[class*="userName"],[class*="nickName"],[data-review],[class*="Comment--"],[data-question],[class*="qaItem--"],[data-answer-text]';
  const visible=e=>{if(!e||e.closest('[hidden],[inert]'))return false;const r=e.getBoundingClientRect();if(r.width<=1||r.height<=1)return false;for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||s.opacity==='0')return false;}return true;};
  const viewport=e=>{const r=e.getBoundingClientRect();return r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth;};
  const safeText=e=>{if(!e||e.closest(privateSelector)||!visible(e))return '';const walker=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);const chunks=[];let node;while((node=walker.nextNode())){const p=node.parentElement;if(p&&!p.closest(privateSelector)&&visible(p))chunks.push(node.textContent);}return scrub(chunks.join(' '));};
  const unique=items=>[...new Map(items.map(x=>[JSON.stringify(x),x])).values()];
  const countPattern='\\d+(?:\\.\\d+)?(?:万|亿|千|百|[kKwW])?\\+?';
  const numberInfo=value=>{const m=value.match(/^(\d+(?:\.\d+)?)(万|亿|千|百|[kKwW])?(\+)?$/);if(!m)return {displayValue:value,numericValue:null,comparison:null,isApproximate:true};const scale={'万':1e4,'亿':1e8,'千':1e3,'百':100,k:1e3,K:1e3,w:1e4,W:1e4};return {displayValue:value,numericValue:Number(m[1])*(scale[m[2]]||1),comparison:m[3]?'at-least':'displayed',isApproximate:!!m[2]||!!m[3]};};
  const periodInfo=raw=>{const m=raw.match(/(近|最近)?(\d+)\s*(小时|天|个月|月|年)(?:内)?/);return {period:m?m[0]:null,periodHours:m&&m[3]==='小时'?Number(m[2]):null};};
  const metricsFrom=(raw,region)=>{
    const result=[],prefix='(?:(?:近|最近)?\\d+\\s*(?:小时|天|个月|月|年)(?:内)?\\s*)?';
    const push=(kind,m,value,unit)=>result.push({kind,raw:m[0],...numberInfo(value),unit:unit||'unknown',...periodInfo(m[0]),scope:region==='shop'?'shop':'product',region,source:'visible-page-text'});
    const kinds={'付款':'payments','下单':'orders','购买':'purchases','看过':'views','浏览':'views','收货':'received'};
    for(const m of raw.matchAll(new RegExp(prefix+'('+countPattern+')\\s*人\\s*(付款|下单|购买|看过|浏览|收货)','g')))push(kinds[m[2]],m,m[1],'people');
    for(const m of raw.matchAll(new RegExp(prefix+'下单\\s*('+countPattern+')\\s*(人|单|件)','g')))push('orders',m,m[1],{'人':'people','单':'orders','件':'items'}[m[2]]);
    for(const m of raw.matchAll(new RegExp('(?:超)?('+countPattern+')\\s*人\\s*(?:加购|加入购物车)','g'))){push('cart-additions',m,m[1],'people');if(m[0].startsWith('超'))Object.assign(result[result.length-1],{comparison:'greater-than',isApproximate:true});}
    for(const m of raw.matchAll(new RegExp(prefix+'(?:已售|累计售出|销量)\\s*('+countPattern+')\\s*(件|单|人)?','g')))push('sales',m,m[1],{'人':'people','单':'orders','件':'items'}[m[2]]);
    for(const m of raw.matchAll(new RegExp('回头客\\s*('+countPattern+')(?:\\s*人)?','g')))result.push({kind:'repeat-customers',raw:m[0],...numberInfo(m[1]),unit:'people',period:null,periodHours:null,scope:region==='shop'?'shop':region==='metrics'?'product':'unverified',region,source:'visible-page-text'});
    if(region==='reviews-summary'||region==='shop'){
      if(region==='reviews-summary')for(const m of raw.matchAll(new RegExp('(?:全部评价|用户评价|宝贝评价|评价总数|评价)\\s*[·•:：]?\\s*[（(]?\\s*('+countPattern+')(?:条)?','g')))push('reviews',m,m[1],'reviews');
      for(const m of raw.matchAll(new RegExp(prefix+'好评率\\s*(?:高达|达到)?\\s*(\\d+(?:\\.\\d+)?)\\s*%','g')))result.push({kind:'positive-rate',raw:m[0],displayValue:m[1]+'%',numericValue:Number(m[1]),unit:'percent',scope:region==='shop'?'shop':'product',region,...periodInfo(m[0]),isApproximate:false,comparison:'displayed',source:'visible-page-text'});
    }
    return result;
  };
  const read=(root,source)=>{
    const entries=[],seen=new Set();
    const reputationPanels=source==='product-detail'?[...root.querySelectorAll('[data-shop-reputation-panel],[class*="shopHeader--"] [class*="StorePopup--"]')].filter(visible):[];
    const add=(e,region)=>{const raw=safeText(e);if(!raw||raw.length>800||seen.has(region+'|'+raw))return;seen.add(region+'|'+raw);entries.push({raw,region,inViewport:viewport(e),source:'visible-page-text'});};
    let shopName=null;
    const nameSelectors='[data-shop-name],[class*="shopNameText--"],.slogo-shopname,.shop-name,[class*="ShopName--"],[class*="shopHeader--"] [class*="shopName--"]';
    const names=[...root.querySelectorAll(nameSelectors)].filter(e=>visible(e)&&!e.closest(privateSelector)&&!e.closest('[data-recommendation],[class*="recommend"],[class*="Recommend"]'));
    const nameCandidates=names.map(safeText).filter(Boolean);if(new Set(nameCandidates).size===1)shopName=nameCandidates[0];
    if(source==='search-card'){
      const excluded='[data-product-title],[class*="title--"],[class*="Title--"],h3';
      for(const e of root.querySelectorAll('span,div,p,a')){
        if(e.children.length||e.closest(excluded)||!visible(e))continue;
        const t=safeText(e);if(t&&t.length<=160)add(e,e.closest('[data-shop-metrics],[class*="shopName--"],[class*="ShopName--"],[class*="shopInfo"],.shop-name')?'shop':'card');
      }
      for(const e of root.querySelectorAll('[class*="tradeInfoWrapper"],[class*="realSales--"],[data-commerce-metrics]'))add(e,'card');
      for(const e of root.querySelectorAll('[class*="rankTitle"],[class*="rankSubTitle"],[data-ranking]'))add(e,'ranking');
      for(const e of root.querySelectorAll('[data-selling-point],[data-selling-points],[class*="text--"]'))add(e,'selling-points');
    }else{
      const selectors={
        shop:'[data-detail-shop],[data-shop-metrics],[data-shop-rating],[class*="ShopInfo"],[class*="shopInfo"],[class*="shopHeader"],[class*="ShopHeader"],.tb-shop-info,#shopExtra',
        metrics:'[data-product-metrics],[data-product-sales],[class*="realSales"],[class*="tradeInfo"],[class*="Sales--"],[class*="sales--"],[class*="sold--"],[class*="ItemTitle--"] [class*="subTitleInnerWrap--"]',
        pricing:'[data-product-price],#J_StrPrice,#J_PromoPrice,[class*="Price--"],[class*="price--"],[class*="priceInfo"],[class*="PriceInfo"]',
        promotions:'[data-product-offer],[data-product-promotion],[class*="coupon"],[class*="Coupon"],[class*="promotion"],[class*="Promotion"]',
        fulfillment:'[data-delivery-time],[data-shipping-fee],[data-fulfillment],[class*="deliveryTime"],[class*="DeliveryTime"],[class*="logistics"],[class*="Logistics"],[class*="shipping"],[class*="freight"]',
        services:'[data-service-text],[class*="guaranteeText--"],[class*="GuaranteeItem--"],[data-service-summary],.tb-service',
        'reviews-summary':'[data-product-review-summary],[class*="reviewSummary"],[class*="rateSummary"],[class*="Comments--"] [class*="title--"],[class*="Comments--"] [class*="titleWrapper--"]',
        ranking:'[data-ranking],[class*="rankTitle"],[class*="rankSubTitle"]',
        'selling-points':'[data-selling-points],[class*="subTitle--"],[class*="subtitle--"]'
      };
      for(const [region,selector] of Object.entries(selectors))for(const e of root.querySelectorAll(selector))add(e,region);
      for(const e of names)add(e,'shop');
    }
    const metrics=unique(entries.flatMap(e=>metricsFrom(e.raw,e.region)));
    const texts=entries.map(e=>e.raw);
    const claims=(pattern,regions=null)=>{const result=[];for(const e of entries){if(regions&&!regions.includes(e.region))continue;for(const m of e.raw.matchAll(pattern))result.push({raw:m[0],region:e.region,source:e.source});}return unique(result);};
    const badges=claims(/品牌旗舰|官方旗舰店|官方直营|天猫国际|企业店|\d+年老店/g,['shop','card']).filter(r=>r.raw!=='官方旗舰店'||shopName?.includes('官方旗舰店'));
    const arrival=claims(/明日达|次日达|今日达|当日达|隔日达|后天达|预计\s*(?:\d{1,2}月)?\d{1,2}日(?:前)?(?:送达|到达)|预计\s*\d{1,2}[-/]\d{1,2}(?:前)?(?:送达|到达)/g);
    const dispatch=claims(/\d+\s*(?:小时|天)内(?:发货|发)|预售\s*\d+\s*天内发货/g);
    const fees=claims(/(?:满\s*[¥￥]?\s*\d+(?:\.\d+)?\s*元?\s*[，,、]?\s*)?包邮|免运费|(?:快递|运费)(?:费)?\s*[:：]?\s*[¥￥]?\s*\d+(?:\.\d+)?\s*元?/g).map(e=>({...e,conditional:/满/.test(e.raw)?true:null,amount:/^(?:包邮|免运费)$/.test(e.raw)?0:(e.raw.match(/(?:快递|运费)(?:费)?\s*[:：]?\s*[¥￥]?\s*(\d+(?:\.\d+)?)/)||[])[1]?Number(e.raw.match(/(?:快递|运费)(?:费)?\s*[:：]?\s*[¥￥]?\s*(\d+(?:\.\d+)?)/)[1]):null}));
    const services=claims(/\d+\s*天无理由(?:退货)?|退货宝|运费险|极速退款|假一赔\s*[四十百\d]+|正品保障|全国联保|\d+\s*天价保|包退|包换|上门取件|上门安装/g);
    const basis=claims(/国补后|补贴后|优惠后|券后|到手价|预估到手|活动价|原价/g);
    const promotions=unique(entries.filter(e=>e.region==='promotions').map(e=>({raw:e.raw,region:e.region,source:e.source})).concat(claims(/(?:国家补贴|政府补贴|超级立减|淘金币抵|直降|已补|满减)[\d.%万+元折]+|\d+期免息/g)));
    const ratingLabels='描述相符|服务体验|物流体验|店铺体验|服务态度|物流服务';
    const ratings=unique(entries.filter(e=>e.region==='shop').flatMap(e=>[...e.raw.matchAll(new RegExp('('+ratingLabels+')\\s*[:：]?\\s*(\\d(?:\\.\\d+)?)','g'))].map(m=>({label:m[1],displayValue:m[2],numericValue:Number(m[2]),scale:null,raw:m[0],scope:'shop',source:e.source}))));
    const reputationRows=[];
    for(const panel of reputationPanels){
      for(const e of panel.querySelectorAll('[data-shop-rating-row],[class*="shopItem--"],[class*="evaluateItem--"]')){
        const raw=safeText(e),m=raw.match(/^(综合体验|宝贝质量|物流速度|服务保障)\s*[:：]?\s*(\d(?:\.\d+)?)$/);
        if(!m)continue;
        const row={label:m[1],displayValue:m[2],numericValue:Number(m[2]),scale:null,raw,scope:'shop',source:'visible-shop-reputation-panel'};
        ratings.push(row);reputationRows.push(row);
      }
    }
    for(const e of [...root.querySelectorAll('[data-shop-score],[class*="StoreComprehensiveRating--"]')].filter(e=>visible(e)&&!e.closest(privateSelector))){const raw=safeText(e),m=raw.match(/^(\d(?:\.\d+)?)$/);if(m)ratings.push({label:'店铺综合评分',displayValue:m[1],numericValue:Number(m[1]),scale:null,raw,scope:'shop',source:'visible-shop-score'});}
    const performance=unique(entries.filter(e=>e.region==='shop').flatMap(e=>[...e.raw.matchAll(/平均\s*(\d+(?:\.\d+)?)\s*(小时|天)\s*(发货|退款)/g)].map(m=>({raw:m[0],kind:m[3]==='发货'?'average-dispatch':'average-refund',duration:Number(m[1]),unit:m[2],scope:'shop',source:e.source,isPromise:false}))));
    const levelNodes=[...root.querySelectorAll('[data-shop-level],[class*="creditLevelIconImg--"]')].filter(e=>visible(e)&&!e.closest(privateSelector));
    const levelTexts=unique(levelNodes.map(e=>scrub(e.getAttribute('aria-label')||e.getAttribute('title')||e.getAttribute('alt')||(e.tagName!=='IMG'?safeText(e):''))).filter(Boolean));
    const levelIcons=levelNodes.filter(e=>e.tagName==='IMG').map(e=>({src:e.currentSrc||e.src||null,width:e.naturalWidth,height:e.naturalHeight,alt:scrub(e.alt),inViewport:viewport(e),ready:!!(e.complete&&e.naturalWidth)}));
    const imageSelector=source==='product-detail'?'[data-product-main-image],#J_ImgBooth,[class*="mainPic"] img,img[class*="mainPic--"],#description img,#J_DivItemDesc img,.desc-root img,.descV8-container img,[data-product-image]':'img';
    const images=[...root.querySelectorAll(imageSelector)].filter(e=>visible(e)&&!e.closest(privateSelector)).slice(0,80).map(e=>{
      const src=e.currentSrc||e.getAttribute('src')||null;return {src:src&&src.length<1600?src:null,width:e.naturalWidth,height:e.naturalHeight,complete:e.complete,ready:!!(e.complete&&e.naturalWidth>0),inViewport:viewport(e),region:source==='search-card'?'search-card':e.closest('#description,#J_DivItemDesc,[data-product-description],.desc-root,.descV8-container')?'description':'gallery',alt:scrub(e.alt).slice(0,200),role:e.naturalWidth>=100&&e.naturalHeight>=100?'product-or-content':e.naturalWidth&&e.naturalHeight?'label-or-icon':'unverified'};
    });
    const originNodes=source==='product-detail'?[...root.querySelectorAll('[data-delivery-summary],[class*="deliveryAddrWrap--"]')].filter(visible):[];
    const origins=unique(originNodes.map(e=>{const t=norm(e.innerText);return /至/.test(t)?scrub(t.split(/\s*至\s*/)[0]).slice(0,40):null;}).filter(Boolean).concat([...root.querySelectorAll('[data-shipping-origin],[class*="procity--"],[class*="proCity--"],[class*="location--"]')].map(safeText).filter(t=>t&&t.length<40)));
    const priceClaims=[];
    if(source==='product-detail')for(const e of [...root.querySelectorAll('[data-product-price],#J_StrPrice,#J_PromoPrice,[class*="Price--"],[class*="price--"]')].filter(visible)){
      const parts=[];let t=safeText(e);for(const struck of [...e.querySelectorAll('del,s')].filter(visible)){const raw=safeText(struck);if(raw){t=t.replace(raw,' ');parts.push({text:raw,role:'struck-through'});}}
      parts.push({text:t,role:e.closest('del,s')?'struck-through':'displayed-unverified'});
      for(const part of parts)for(const m of part.text.replace(/(\d)\s*\.\s*(\d)/g,'$1.$2').matchAll(/[¥￥]\s*(\d+(?:\.\d+)?)/g))priceClaims.push({raw:m[0],amount:Number(m[1]),currency:'CNY',role:part.role,source:'visible-price-region'});
    }
    return {schemaVersion:1,source,shop:{name:shopName,badges,repeatCustomers:metrics.filter(m=>m.kind==='repeat-customers'&&m.scope==='shop'),ratings:unique(ratings),performance,
      reputation:{panelVisible:reputationPanels.length>0,panelInViewport:reputationPanels.some(viewport),panelCount:reputationPanels.length,rows:unique(reputationRows),source:'loaded-visible-dom-text',unverified:['credit score not shown by this panel','rating scale unless explicitly labelled']},
      level:{text:levelTexts.length===1?levelTexts[0]:null,status:levelTexts.length===1?'page-label':levelIcons.length?'image-only-unverified':'not-observed',icons:levelIcons,source:'visible-level-region'}},metrics,
      fulfillment:{origins,destination:'redacted',arrivalPromises:arrival,dispatchPromises:dispatch,shippingFees:fees,conditionsVerified:false},
      pricing:{basis,promotions,priceClaims:unique(priceClaims),finalPrice:null,eligibilityVerified:false},services,
      rankings:entries.filter(e=>e.region==='ranking').map(e=>({raw:e.raw,source:e.source})),
      sellingPoints:entries.filter(e=>e.region==='selling-points').map(e=>e.raw).slice(0,30),
      labels:entries.slice(0,100),media:{images,readyImageCount:images.filter(i=>i.ready).length,pendingImageCount:images.filter(i=>!i.ready).length},
      coverage:{loadedDomOnly:true,absenceMeans:'not observed, not zero or unsupported',imageOnlyText:'not OCRed',privacy:'destination and buyer identities excluded',truncated:entries.length>100,claimsVerified:false}};
  };
  if(options.mode==='detail')return read(document,'product-detail');
  const products=[],seen=new Set();
  for(const a of document.querySelectorAll('a[href]')){
    let u;try{u=new URL(a.href);}catch{continue}const id=u.searchParams.get('id');
    if(!['item.taobao.com','detail.tmall.com'].includes(u.hostname)||u.pathname!=='/item.htm'||!/^\d+$/.test(id||'')||seen.has(id)||!visible(a))continue;
    seen.add(id);const root=a.closest('[data-product-card],[class*="doubleCardWrapper"],[class*="cardItem"],li')||a;
    products.push({productId:id,commerce:read(root,'search-card'),rendered:true,inViewport:viewport(root)});if(products.length>=100)break;
  }
    return products;
}
// HUOYAN_DOM_END
module.exports={readCommerceEvidence};
