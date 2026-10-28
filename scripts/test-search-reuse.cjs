const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');
const browserModule = require('../src/core/browser');
const { openStartPage } = require('../src/core/searchPage');
const { detectBlockingState, createBlockedError } = require('../src/core/collector');
const { waitRandom, actionDelayRange } = require('../src/core/pacing');

const html = `<html><body style="height:4000px">
<form target="_blank" action="/search.htm"><input name="keyword"><button type="submit" formtarget="_blank">搜索</button></form>
<form action="/search"><input name="q"><button type="submit">全站搜索</button></form>
<div id="results"></div><script>
window.searches=[]; window.scrolls=0;
window.addEventListener('scroll',()=>window.scrolls++);
document.querySelectorAll('form').forEach(form=>form.addEventListener('submit',event=>{
 event.preventDefault(); const input=form.querySelector('input');
 window.searches.push({field:input.name,keyword:input.value,target:form.target});
 document.querySelector('#results').textContent='结果: '+input.value;
 history.pushState({},'',form.action+'?'+input.name+'='+encodeURIComponent(input.value));
}));</script></body></html>`;

(async () => {
  const originalRandom = Math.random;
  const waits = [];
  try {
    Math.random = () => 0;
    await waitRandom({ waitForTimeout: async ms => waits.push(ms) });
    Math.random = () => 0.99999999;
    await waitRandom({ waitForTimeout: async ms => waits.push(ms) });
  } finally { Math.random = originalRandom; }
  assert.deepEqual(waits, [2500, 4500]);
  assert.deepEqual(actionDelayRange(), { min: 12000, max: 25000 });
  console.log('PASS random waits reach both range boundaries and use lower-frequency defaults');
  const socket = require('node:net').createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const browser = await chromium.launch({ executablePath: browserModule.getDefaultEdgePath(), headless: true,
    args: ['--no-proxy-server', '--enable-automation', `--remote-debugging-port=${port}`, '--remote-debugging-address=127.0.0.1'] });
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'huoyan-search-test-'));
  try {
    const context = await browser.newContext();
    await context.route('**/*', route => route.fulfill({ contentType: 'text/html; charset=utf-8', body: html }));
    const realNewPage = context.newPage.bind(context);
    context.newPage = async () => {
      const page = await realNewPage();
      page.waitForTimeout = async () => {};
      return page;
    };
    const existing = await context.newPage();
    existing.waitForTimeout = async () => {};
    await existing.goto('https://youxin-electronic.taobao.com/search.htm?keyword=old');
    const unrelated = await context.newPage();
    await unrelated.goto('https://other-shop.taobao.com/search.htm');
    const options = { site: 'taobao', startUrl: 'https://youxin-electronic.taobao.com/search.htm?keyword=next', openSearch: true };
    const hooks = { detectBlockingState, createBlockedError };
    let page;
    for (const keyword of ['XT30', '0805 22K']) {
      const selected = await openStartPage(browser, options, keyword, hooks);
      if (!page) {
        assert.equal(selected.page, existing);
        assert.equal(selected.reused, true);
        page = selected.page;
      } else {
        assert.equal(selected.page, page);
        assert.equal(selected.reused, true);
      }
      assert(selected.beforeSearchWaitMs >= 12000 && selected.beforeSearchWaitMs <= 25000);
      assert(selected.waitMs >= 2500 && selected.waitMs <= 4500);
      assert.equal(selected.action, 'click-search');
    }
    assert.equal(context.pages().length, 2);
    assert.deepEqual(await page.evaluate(() => window.searches), [
      { field: 'keyword', keyword: 'XT30', target: '_self' },
      { field: 'keyword', keyword: '0805 22K', target: '_self' }
    ]);
    assert.equal(await unrelated.evaluate(() => window.searches.length), 0);

    console.log('PASS existing search form is reused from the first search; unrelated tabs are preserved');

    // Exercise collect twice without creating or closing the search tab.
    const originalAcquire = browserModule.acquireBrowser;
    browserModule.acquireBrowser = async options => {
      assert.equal(options.browserMode, 'cdp');
      return { source: 'cdp', browser: { contexts: () => [context], close: async () => {} } };
    };
    delete require.cache[require.resolve('../src/core/collector')];
    const { collect } = require('../src/core/collector');
    const events = [];
    for (const keyword of ['电阻', '连接器']) {
      await collect({ ...options, keyword, out, format: 'jsonl', interactiveLogin: false }, {
        log: (name, payload) => events.push({ name, payload })
      });
    }
    browserModule.acquireBrowser = originalAcquire;
    assert.equal(context.pages().length, 2);
    assert.equal(await page.evaluate(() => window.searches.length), 4);
    assert.equal(events.filter(e => e.name === 'page_scroll').length, 2);
    assert(events.filter(e => e.name === 'page_scroll').every(e =>
      e.payload.plannedCount >= 2 && e.payload.plannedCount <= 5
      && e.payload.count > 0 && e.payload.count <= e.payload.plannedCount));
    assert(await page.evaluate(() => window.scrollY) > 0);
    assert(events.filter(e => e.name === 'page_scroll').every(e => e.payload.steps.every(step =>
      (step.direction === 'down' ? step.screenPercent >= 50 && step.screenPercent <= 250
        : step.screenPercent >= 20 && step.screenPercent <= 50)
      && step.waitMs >= 350 && step.waitMs <= 800)));
    console.log('PASS full collector repeats searches without duplicate submits and scrolls by default');

    await page.evaluate(() => document.querySelector('#results').textContent = '安全验证');
    await assert.rejects(openStartPage(browser, options, 'blocked', hooks), error => error.exitCode === 2);
    assert.equal(await page.evaluate(() => window.searches.length), 4);
    console.log('PASS verification stops before any new search');

    await page.evaluate(() => { document.body.innerHTML = '<p>No search box</p>'; });
    await assert.rejects(openStartPage(browser, options, 'missing', hooks), /No usable search input/);
    assert.equal(context.pages().length, 2);
    console.log('PASS missing search control fails without opening a new tab or direct search URL');

    const global = await context.newPage();
    await global.goto('https://s.taobao.com/search?q=old');
    global.waitForTimeout = async () => {};
    const selected = await openStartPage(browser, { site: 'taobao' }, '电容', hooks);
    assert.equal(selected.page, global);
    const dedicatedGlobal = selected.page;

    assert.equal(await dedicatedGlobal.locator('#results').textContent(), '结果: 电容');
    assert.equal(await dedicatedGlobal.evaluate(() => window.searches[0].field), 'q');
    console.log('PASS global search uses q instead of a shop keyword field');

    const initialCount = context.pages().length;
    await assert.rejects(openStartPage(browser, { site: 'jd', delayMin: 0, delayMax: 0 }, 'PLA', hooks), /only the first Taobao homepage/);
    assert.equal(context.pages().length, initialCount);
    console.log('PASS missing other site entry cannot open a page automatically');

    const blank = await context.newPage();
    const beforeBlankReuse = context.pages().length;
    await assert.rejects(openStartPage(browser, { site: 'goofish', delayMin: 0, delayMax: 0 }, '钩子', hooks), /only the first Taobao homepage/);
    assert.equal(context.pages().length, beforeBlankReuse);
    assert.equal(blank.url(),'about:blank');
    console.log('PASS blank tab cannot bypass the homepage-only navigation policy');

    const connection = await browserModule.acquireBrowser({ browserMode: 'cdp', cdp: `http://127.0.0.1:${port}` });
    await connection.browser.close();
    assert.equal(dedicatedGlobal.isClosed(), false);
    assert.equal(await dedicatedGlobal.locator('#results').textContent(), '结果: 电容');
    const reconnect = await browserModule.acquireBrowser({ browserMode: 'cdp', cdp: `http://127.0.0.1:${port}` });
    assert((await browserModule.getOpenPages(reconnect.browser)).some(p => p.url() === dedicatedGlobal.url()));
    const beforeCount = context.pages().length;
    const reused = await openStartPage(reconnect.browser, { site: 'taobao', delayMin: 0, delayMax: 0 }, 'PLA', hooks);
    assert.equal(reused.reused, true);
    assert.equal(context.pages().length, beforeCount);
    assert.equal(await dedicatedGlobal.locator('#results').textContent(), '结果: PLA');
    await reconnect.browser.close();
    console.log('PASS actual CDP disconnect keeps Edge and the search tab alive for reconnection');
  } finally {
    await browser.close();
    fs.rmSync(out, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
