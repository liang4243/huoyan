const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');
const { getDefaultEdgePath } = require('../src/core/browser');
const { acquireProductPage, rememberProduct, readRegistry, productIdentity } = require('../src/core/productTabs');

(async () => {
  assert.equal(productIdentity('https://item.taobao.com/item.htm?id=123&spm=aaa').key,
    productIdentity('https://detail.tmall.com/item.htm?id=123&spm=bbb').key);
  assert.notEqual(productIdentity('https://item.jd.com/123.html').key, productIdentity('123').key);
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'huoyan-tabs-'));
  const browser = await chromium.launch({ executablePath: getDefaultEdgePath(), headless: true });
  try {
    const context = await browser.newContext();
    let requests = 0;
    await context.route('**/*', route => {
      requests++;
      return route.fulfill({ contentType: 'text/html; charset=utf-8', body: `<title>PLA</title>
        <p data-product-price>￥${requests * 10}</p><p data-product-offer>优惠券5元</p><p data-product-stock>库存20</p>` });
    });
    const realNewPage = context.newPage.bind(context);
    context.newPage = async () => { const page = await realNewPage(); page.waitForTimeout = async () => {}; return page; };
    const options = { out, delayMin: 0, delayMax: 0 };
    const userOpened=await context.newPage();
    await userOpened.goto('https://item.taobao.com/item.htm?id=123');
    const first = await acquireProductPage(browser, '123', options);
    const snapshot = await rememberProduct(first.page, first.registry, options);
    assert(snapshot.tabId);
    assert.equal(snapshot.productId, '123');
    assert.deepEqual(snapshot.prices, ['￥10']);
    assert.deepEqual(snapshot.offers, ['优惠券5元']);
    assert.deepEqual(snapshot.stock, ['库存20']);
    const again = await acquireProductPage(browser, 'https://detail.tmall.com/item.htm?id=123&spm=tracking', options);
    assert.equal(again.page, first.page);
    assert.equal(requests, 1);
    assert.equal(context.pages().length, 1);
    console.log('PASS tracking links deduplicate by product ID; existing tab read does not reload');

    const refreshed = await acquireProductPage(browser, '123', { ...options, fresh: true });
    assert.equal(refreshed.page, first.page);
    assert.equal(requests, 2);
    const current = await rememberProduct(refreshed.page, refreshed.registry, options);
    assert.deepEqual(current.prices, ['￥20']);
    assert.equal(current.tabId, snapshot.tabId);
    assert.equal(context.pages().length, 1);
    console.log('PASS fresh data reloads original tab and updates price, offers and stock snapshot');

    await first.page.goto('https://item.taobao.com/item.htm?id=456');
    const other = await acquireProductPage(browser, '456', options);
    assert.equal(other.page, first.page);
    let registry = await readRegistry(options);
    assert.equal(registry.tabs[snapshot.tabId].productId, '456');
    assert.deepEqual(registry.products['taobao:123'].tabIds, []);
    const cached = await acquireProductPage(browser, '123', options);
    assert.equal(cached.source, 'cache');
    assert.deepEqual(cached.cache.prices, ['￥20']);
    assert.equal(requests, 3);
    await rememberProduct(other.page, other.registry, options);
    await other.page.close();
    assert.equal((await acquireProductPage(browser, '456', options)).source, 'cache');
    assert.equal(context.pages().length, 0);
    assert.equal(requests, 3);
    console.log('PASS navigation updates mapping; closed or repurposed tabs use local cache without loading');

    await assert.rejects(acquireProductPage(browser,'123',{...options,fresh:true}),/direct product navigation/);
    assert.equal(context.pages().length,0);
    const listing=await context.newPage();
    await listing.goto('https://www.taobao.com/');requests--;
    await listing.setContent('<a href="https://item.taobao.com/item.htm?id=123">商品123</a>');
    const reopened = await acquireProductPage(browser, '123', { ...options, fresh: true });
    assert.equal(reopened.source, 'clicked-link');
    assert.equal(requests, 4);
    assert.notEqual((await rememberProduct(reopened.page, reopened.registry, options)).tabId, snapshot.tabId);
    registry = await readRegistry(options);
    assert.equal(registry.products['taobao:123'].tabIds.length, 1);
    console.log('PASS closed product reopens only when fresh data explicitly requested');

    const external = await context.newPage();
    await external.goto('https://item.jd.com/999.html?utm_source=test');
    const externalRead = await acquireProductPage(browser, 'https://item.jd.com/999.html', options);
    assert.equal(externalRead.page, external);
    assert.equal(context.pages().length, 2);
    assert.equal(requests, 5);
    console.log('PASS first product lookup reuses a user-opened tab');

    const browserModule = require('../src/core/browser');
    const originalAcquire = browserModule.acquireBrowser;
    browserModule.acquireBrowser = async () => ({ source: 'cdp', browser: { contexts: () => [context], close: async () => {} } });
    const { inspectProduct } = require('../src/core/productResearch');
    try {
      await reopened.page.evaluate(()=>{const a=document.createElement('a');a.href='https://item.taobao.com/item.htm?id=321';a.target='_blank';a.textContent='商品321';document.body.append(a)});
      const pair = await Promise.all([
        inspectProduct({ ...options, item: '321' }),
        inspectProduct({ ...options, item: 'https://item.taobao.com/item.htm?id=321&spm=promo' })
      ]);
      assert.equal(requests, 6);
      assert.equal(pair[0].source, 'clicked-link');
      assert.equal(pair[1].source, 'existing-tab');
      assert.equal(pair[0].product.tabId, pair[1].product.tabId);
      console.log('PASS concurrent product research calls share one tab and one initial load');
    } finally { browserModule.acquireBrowser = originalAcquire; }
  } finally {
    await browser.close();
    fs.rmSync(out, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
