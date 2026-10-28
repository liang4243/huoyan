// A single DOM implementation keeps SKU discovery, clicks and verification
// on the same groups. This function runs inside the item page.
// HUOYAN_DOM_BEGIN
function inspectItemPage({ operation, groupIndex, value, count, action }) {
  const visible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
  };
  const text = (el) => (el.innerText || '').replace(/\s+/g, ' ').trim();
  const norm = (s) => String(s || '').replace(/\s+/g, '').replace(/（/g, '(').replace(/）/g, ')');
  const disabled = (el) => el.disabled || el.getAttribute('aria-disabled') === 'true'
    || Array.from(el.classList).some(c => /^(?:(?:is)?disabled|tb-out-of-stock)(?:--|$)/i.test(c));
  const selected = (el) => el.getAttribute('aria-checked') === 'true'
    || el.getAttribute('aria-selected') === 'true'
    || Array.from(el.classList).some(c => /^(?:(?:is)?(?:selected|active|current|checked)|tb-selected)(?:--|$)/i.test(c));

  const groups = () => {
    const nodes = Array.from(document.querySelectorAll('#J_isku .J_TSaleProp, [class*="skuItem"], [class*="SkuItem"]'))
      .filter(n => visible(n) && !n.parentElement?.closest('#J_isku .J_TSaleProp, [class*="skuItem"], [class*="SkuItem"]'));
    return nodes.map(node => {
      const candidates = Array.from(node.querySelectorAll('li, [class*="valueItem"], [class*="ValueItem"], [role="radio"], a'))
        .filter(el => visible(el) && text(el));
      const options = candidates.filter(el => !candidates.some(parent => parent !== el && parent.contains(el)));
      const unique = options.filter((el, i) => options.findIndex(other => norm(text(other)) === norm(text(el))) === i);
      return { node, options: unique, label: text(node.querySelector('[class*="name"], [class*="label"], .tb-metatit') || node).slice(0, 30) };
    }).filter(g => g.options.length);
  };
  const choices = () => groups().filter(g => g.options.length > 1);
  const quantityInput = () => Array.from(document.querySelectorAll(
    '#J_IptAmount, input[class*="countValue"], input[class*="CountValue"], input[name="quantity"], input[class*="quantity"], input[class*="Quantity"], input[class*="amount"], input[class*="Amount"]'
  )).find(el => visible(el) && !disabled(el) && !el.readOnly);
  const favorite = () => {
    const nodes = Array.from(document.querySelectorAll(
      '#J_Favorite, #collectBtn, [class*="collect"], [class*="Collect"], [class*="favorite"], [class*="Favorite"], [class*="RightButton--"], [class*="rightButton--"]'
    )).filter(el => visible(el) && !disabled(el)
      && !/shop|store/i.test(el.id + ' ' + String(el.className))
      && !el.closest('[class*="collectShop"], [class*="favoriteShop"], [class*="shopCollect"], #J_CollectShop')
      && /^(?:收藏|收藏商品|已收藏|取消收藏)$/.test(text(el)));
    return nodes.find(el => el.id === 'J_Favorite') || nodes.find(el => el.tagName === 'BUTTON') || nodes[0];
  };
  const favorited = (target) => target && (/^(?:已收藏|取消收藏)$/.test(text(target))
    || target.getAttribute('aria-pressed') === 'true'
    || Boolean(target.querySelector('.icon-taobaoyishoucang')));
  const successNodes = (kind) => Array.from(document.querySelectorAll('button, div, span, p, a'))
    .filter(el => visible(el) && (kind === 'cart'
      ? /^(?:成功加入购物车|加入购物车成功|已成功加入购物车)[！!。]?$/.test(text(el))
      : /^(?:商品收藏成功|收藏商品成功|收藏成功)[！!。]?$/.test(text(el))))
    .map(el => ({ el, text: text(el) }));

  if (operation === 'groups') return choices().map(g => ({ label: g.label, options: g.options.map(text) }));
  const elementPath = el => { const parts=[];for(let n=el;n&&n!==document.documentElement;n=n.parentElement){parts.unshift(n.tagName.toLowerCase()+':nth-child('+([...n.parentElement.children].indexOf(n)+1)+')');}return 'html > '+parts.join(' > '); };
  if (operation === 'option-controls') return choices().flatMap((g,groupIndex)=>g.options.map(el=>({groupIndex,groupLabel:g.label,text:text(el),disabled:Boolean(disabled(el)),selected:Boolean(selected(el)),elementPath:elementPath(el)})));
  if (operation === 'click-sku' || operation === 'selected-sku') {
    const group = choices()[groupIndex];
    if (!group) return operation === 'selected-sku' ? false : { clicked: false, reason: 'group-not-found', available: [] };
    const matches = group.options.filter(el => norm(text(el)) === norm(value));
    const target = matches.length === 1 ? matches[0] : null;
    if (operation === 'selected-sku') return Boolean(target && !disabled(target) && selected(target));
    if (!target || disabled(target)) return { clicked: false, reason: target ? 'option-disabled' : 'option-not-found', available: group.options.map(text) };
    const before = target.className;
    target.scrollIntoView({ block: 'center' });
    if (!selected(target)) target.click();
    return { clicked: true, matchedText: text(target), classNameBefore: String(before) };
  }
  if (operation === 'single-skus') {
    for (const group of groups().filter(g => g.options.length === 1)) {
      const target = group.options[0];
      if (disabled(target)) return { ok: false, reason: 'single-option-disabled', label: group.label };
      if (!selected(target)) target.click();
    }
    return { ok: true };
  }
  if (operation === 'all-selected') return groups().every(g => g.options.some(el => !disabled(el) && selected(el)));
  if (operation === 'set-quantity') {
    const input = quantityInput();
    if (!input) return { set: false, reason: 'quantity-input-not-found' };
    input.focus();
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, String(count));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    input.blur();
    return { set: input.value === String(count), value: input.value };
  }
  if (operation === 'quantity') return quantityInput()?.value ?? null;
  if (operation === 'snapshot') {
    window.__huoyanItemEvidence = { action, before: new Map(successNodes(action).map(({el, text}) => [el, text])) };
    return true;
  }
  if (operation === 'cart-evidence' || operation === 'favorite-evidence') {
    const kind = operation === 'cart-evidence' ? 'cart' : 'fav';
    if (kind === 'fav') {
      const target = favorite();
      if (favorited(target)) return 'already-state';
    }
    const baseline = window.__huoyanItemEvidence;
    const fresh = successNodes(kind).some(({el, text}) => !baseline || baseline.action !== kind || baseline.before.get(el) !== text);
    return fresh ? 'success-text' : null;
  }
  if (operation === 'favorite') {
    const target = favorite();
    if (!target) return { clicked: false, reason: 'favorite-button-not-found' };
    if (favorited(target)) return { clicked: false, already: true };
    target.scrollIntoView({ block: 'center' });
    target.click();
    return { clicked: true, text: text(target), cls: String(target.className) };
  }
  if (operation === 'cart') {
    const nodes = Array.from(document.querySelectorAll('#J_JoinCart, button, a, div, span'))
      .filter(el => visible(el) && !disabled(el) && /^(?:加入购物车|加入淘宝购物车)$/.test(norm(text(el))))
      .sort((a,b) => Number(b.tagName === 'BUTTON') - Number(a.tagName === 'BUTTON'));
    const target = nodes[0];
    if (!target) return { clicked: false, reason: 'cart-button-not-found' };
    target.scrollIntoView({ block: 'center' });
    target.click();
    return { clicked: true, tag: target.tagName, id: target.id, cls: String(target.className) };
  }
  throw new Error(`Unknown DOM operation: ${operation}`);
}

// HUOYAN_DOM_END
const inspect = (page, operation, args = {}) => page.evaluate(inspectItemPage, { operation, ...args });
module.exports = { inspect };
