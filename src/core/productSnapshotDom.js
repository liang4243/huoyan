// HUOYAN_DOM_BEGIN
function readProductDom() {
    const visible = el => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const texts = selectors => [...new Set(Array.from(document.querySelectorAll(selectors))
      .filter(visible).map(el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean).map(text => text.slice(0, 500)))].slice(0, 12);
    const result = {
      title: document.querySelector('meta[property="og:title"]')?.content || document.title,
      description: texts('[data-product-description], #J_DivItemDesc, #description, .desc-root, .descV8-container, [class*="Description"], [class*="description"]').join('\n').slice(0, 8000),
      skuCandidates: Array.from(document.querySelectorAll('#J_isku .J_TSaleProp, [class*="skuItem"], [class*="SkuItem"]'))
        .filter(visible).filter(el => !el.parentElement?.closest('#J_isku .J_TSaleProp, [class*="skuItem"], [class*="SkuItem"]'))
        .map(group => ({ label: (group.querySelector('[class*="name"], [class*="label"], .tb-metatit')?.innerText || '').trim(),
          options: Array.from(group.querySelectorAll('li, [class*="valueItem"], [class*="ValueItem"], [role="radio"], a'))
            .filter(visible).filter(el => !Array.from(group.querySelectorAll('li, [class*="valueItem"], [class*="ValueItem"], [role="radio"], a')).some(parent => parent !== el && parent.contains(el)))
            .map(el => ({ text: (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim(),
              disabled: Boolean(el.disabled || el.getAttribute('aria-disabled') === 'true' || Array.from(el.classList).some(c=>/^(?:(?:is)?disabled|tb-out-of-stock)(?:--|$)/i.test(c))),
              selected: el.getAttribute('aria-checked') === 'true' || el.getAttribute('aria-selected') === 'true' || Array.from(el.classList).some(c=>/^(?:(?:is)?(?:selected|active|current|checked)|tb-selected)(?:--|$)/i.test(c)) }))
            .filter(option => option.text) })).filter(group => group.options.length),
      prices: texts('[data-product-price], #J_StrPrice, #J_PromoPrice, .p-price, [class*="Price--"], [class*="price--"]'),
      offers: texts('[data-product-offer], [class*="coupon"], [class*="Coupon"], [class*="promotion"], [class*="Promotion"]'),
      stock: texts('[data-product-stock], #J_EmStock, #store-prompt, [class*="stock"], [class*="Stock"]'),
      selectedSku: Array.from(document.querySelectorAll('#J_isku .J_TSaleProp li,[class*="skuItem"] [class*="valueItem"],[class*="skuItem"] li,[class*="SkuItem"] [class*="ValueItem"],[class*="skuItem"] [role="radio"]')).filter(visible).filter(el=>el.getAttribute('aria-checked')==='true'||el.getAttribute('aria-selected')==='true'||Array.from(el.classList).some(c=>/^(?:(?:is)?(?:selected|active|current|checked)|tb-selected)(?:--|$)/i.test(c))).map(el=>(el.innerText||'').replace(/\s+/g,' ').trim()).filter(Boolean)
    };
    result.selectedSku = result.skuCandidates.flatMap(group => group.options.filter(option => option.selected).map(option => option.text));
    return result;
}
// HUOYAN_DOM_END
module.exports = { readProductDom };
