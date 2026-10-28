// HUOYAN_DOM_BEGIN
function readImageResearchDom() {
  const norm=s=>String(s||'').replace(/\s+/g,' ').trim();
  const visible=e=>{if(!e||e.closest('[hidden],[inert],[data-private],[data-review],[class*="Comment--"],[data-recommendation],[class*="recommend"],[class*="Recommend"]'))return false;const r=e.getBoundingClientRect();if(r.width<=1||r.height<=1)return false;for(let p=e;p;p=p.parentElement){const s=getComputedStyle(p);if(s.display==='none'||s.visibility==='hidden'||s.opacity==='0')return false;}return true;};
  const path=e=>{const a=[];for(let n=e;n&&n!==document.documentElement;n=n.parentElement){if(!n.parentElement)return null;a.unshift(n.tagName.toLowerCase()+':nth-child('+([...n.parentElement.children].indexOf(n)+1)+')');}return 'html > '+a.join(' > ');};
  const selected=e=>e.getAttribute('aria-selected')==='true'||e.getAttribute('aria-checked')==='true'||[...e.classList].some(c=>/^(?:(?:is)?(?:selected|active|current|checked)|tb-selected)(?:--|$)/i.test(c));
  const images=[];
  const add=(img,source,extra={})=>{if(img?.tagName!=='IMG'||!visible(img))return;const src=img.currentSrc||img.src;if(!src||src.length>8000)return;const r=img.getBoundingClientRect();images.push({elementPath:path(img),src,source,label:norm(img.alt).slice(0,160)||source,width:img.naturalWidth,height:img.naturalHeight,ready:!!(img.complete&&img.naturalWidth>0&&img.naturalHeight>0),renderedWidth:r.width,renderedHeight:r.height,inViewport:r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth,skuAssociation:'unverified',...extra});};
  const groups=[...document.querySelectorAll('#J_isku .J_TSaleProp,[class*="skuItem"],[class*="SkuItem"]')].filter(e=>!e.parentElement?.closest('#J_isku .J_TSaleProp,[class*="skuItem"],[class*="SkuItem"]'));
  for(const [groupIndex,g] of groups.entries()){
    const groupLabel=norm(g.querySelector('[class*="label"],[class*="name"],.tb-metatit')?.innerText)||'规格'+(groupIndex+1);
    for(const img of g.querySelectorAll('img')){const option=img.closest('li,[class*="valueItem--"],[class*="ValueItem--"],[role="radio"],a');if(!option||!g.contains(option))continue;const label=norm(option.innerText||option.title||img.alt).slice(0,180);if(!label)continue;add(img,'sku',{label,groupIndex,groupLabel,skuOption:label,selected:selected(option),disabled:option.getAttribute('aria-disabled')==='true'||option.getAttribute('data-disabled')==='true'||[...option.classList].some(c=>/^(?:is)?disabled(?:--|$)/i.test(c)),skuAssociation:'displayed-option-thumbnail; not a full SKU combination'});}
  }
  for(const e of document.querySelectorAll('[data-product-main-image],#J_ImgBooth,.tb-booth img,[class*="mainPic"] img,img[class*="mainPic--"],[data-product-thumbnail],#J_UlThumb li,[class*="thumbnail"] img,[class*="Thumbnail"] img'))add(e.tagName==='IMG'?e:e.querySelector('img'),'gallery');
  for(const e of document.querySelectorAll('#description img,#J_DivItemDesc img,.desc-root img,.descV8-container img,[data-product-description] img,[data-product-image]'))add(e,'description');
  return images.slice(0,160);
}
// HUOYAN_DOM_END
module.exports={readImageResearchDom};
