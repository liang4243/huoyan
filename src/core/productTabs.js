const { readProductDom } = require('./productSnapshotDom');
const path = require('path');
const fs = require('fs-extra');
const { getOpenPages, waitForPageReady } = require('./browser');
const { productIdentity } = require('./productIdentity');
const { actionDelayRange, waitRandom } = require('./pacing');

function registryPath(options = {}) {
  return path.resolve(options.out || 'data', 'product-tabs.json');
}

async function readRegistry(options) {
  const file = registryPath(options);
  if (!await fs.pathExists(file)) return { version: 1, tabs: {}, products: {} };
  const registry = await fs.readJson(file);
  if (registry.version !== 1 || !registry.tabs || !registry.products) throw new Error('Invalid product tab registry.');
  return registry;
}

async function saveRegistry(registry, options) {
  const file = registryPath(options);
  const temporary = `${file}.${process.pid}.tmp`;
  await fs.outputJson(temporary, registry, { spaces: 2 });
  await fs.move(temporary, file, { overwrite: true });
}

async function tabId(page) {
  const session = await page.context().newCDPSession(page);
  try { return (await session.send('Target.getTargetInfo')).targetInfo.targetId; }
  finally { await session.detach(); }
}

async function syncTabs(browser, registry, options = {}) {
  const endpoint = options.cdp || 'http://127.0.0.1:9222';
  for (const [id, tab] of Object.entries(registry.tabs)) {
    if (tab.endpoint === endpoint) delete registry.tabs[id];
  }
  const live = new Map();
  for (const page of await getOpenPages(browser)) {
    let identity;
    try { identity = productIdentity(page.url()); } catch { continue; }
    const id = await tabId(page);
    registry.tabs[id] = { productKey: identity.key, productId: identity.productId, url: page.url(), endpoint };
    const product = registry.products[identity.key] ||= { ...identity, tabIds: [] };
    product.url = page.url();
    if (!live.has(identity.key)) live.set(identity.key, { page, tabId: id, identity });
  }
  for (const product of Object.values(registry.products)) product.tabIds = [];
  for (const [id, tab] of Object.entries(registry.tabs)) registry.products[tab.productKey]?.tabIds.push(id);
  await saveRegistry(registry, options);
  return live;
}

async function readSnapshot(page, identity, id) {
  const details = await page.evaluate(readProductDom);
  return { productId: identity.productId, productKey: identity.key, url: page.url(), tabId: id,
    observedAt: new Date().toISOString(), ...details,
    note: 'Visible page text only; empty fields mean not found. Price may depend on SKU, coupons, login and checkout.' };
}

async function rememberProduct(page, registry, options = {}) {
  const identity = productIdentity(page.url());
  const id = await tabId(page);
  const cache = await readSnapshot(page, identity, id);
  registry.tabs[id] = { productKey: identity.key, productId: identity.productId, url: page.url(),
    endpoint: options.cdp || 'http://127.0.0.1:9222' };
  const product = registry.products[identity.key] ||= { ...identity, tabIds: [] };
  product.url = page.url();
  product.cache = cache;
  for (const entry of Object.values(registry.products)) entry.tabIds = [];
  for (const [target, tab] of Object.entries(registry.tabs)) registry.products[tab.productKey]?.tabIds.push(target);
  await saveRegistry(registry, options);
  return cache;
}

async function acquireProductPage(browser, item, options = {}) {
  const identity = productIdentity(item);
  const registry = await readRegistry(options);
  const previous = registry.products[identity.key];
  const live = await syncTabs(browser, registry, options);
  const existing = live.get(identity.key);
  if (existing) {
    await existing.page.bringToFront();
    await waitForPageReady(existing.page);
    if (options.fresh) {
      await options.checkPage?.(existing.page);
      const { min, max } = actionDelayRange(options);
      await waitRandom(existing.page, min, max);
      await options.checkPage?.(existing.page);
      if (productIdentity(existing.page.url()).key !== identity.key) {
        await syncTabs(browser, registry, options);
        throw new Error('Product tab navigated elsewhere during refresh pause. Retry to update its mapping.');
      }
      await existing.page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
      await waitRandom(existing.page);
    }
    return { page: existing.page, registry, identity, source: options.fresh ? 'refreshed-tab' : 'existing-tab' };
  }
  // Reads of previously visited, closed products must not silently reopen them.
  if (options.requirePage && !options.fresh && previous) throw new Error('Product tab is closed. Read cache or request fresh; reopening still requires a visible in-page link.');
  if (!options.requirePage && !options.fresh && previous) {
    if (!previous.cache) throw new Error('Product tab is closed and no local snapshot exists. Use fresh to reopen explicitly.');
    return { cache: previous.cache, registry, identity, source: 'cache' };
  }
  let page, link;
  for (const candidate of await getOpenPages(browser)) {
    if (!/^https:\/\/(?:[^/.]+\.)*(?:taobao|tmall)\.com\//.test(candidate.url())) continue;
    const links = candidate.locator('a[href]');
    const items = await links.evaluateAll(els => els.map((e,index) => ({index,href:e.href,visible:e.getBoundingClientRect().width>1 && e.getBoundingClientRect().height>1})));
    for (const entry of items) {
      if (!entry.visible || !entry.href.startsWith('https://')) continue;
      try { if (productIdentity(entry.href).key === identity.key) { page=candidate; link=links.nth(entry.index); break; } } catch {}
    }
    if (link) break;
  }
  if (!link) throw new Error('No visible in-page product link. Search first; direct product navigation is forbidden.');
  await options.checkPage?.(page);
  const { min, max } = actionDelayRange(options);
  await waitRandom(page, min, max);
  await options.checkPage?.(page);
  if (productIdentity(await link.evaluate(e=>e.href)).key !== identity.key || !await link.isVisible()) throw new Error('Product link changed; no click performed.');
  await link.click({timeout:8000});
  await waitRandom(page);
  let opened;
  for (let attempt=0;attempt<50;attempt++) {
    opened=(await syncTabs(browser,registry,options)).get(identity.key);
    if(opened) break;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  if (!opened) throw new Error('Product link did not reach the requested product; no direct URL fallback.');
  await waitForPageReady(opened.page);
  await options.checkPage?.(opened.page);
  await opened.page.bringToFront();
  return { page:opened.page, registry, identity, source: 'clicked-link' };
}

module.exports = { acquireProductPage, rememberProduct, syncTabs, readRegistry, productIdentity };
