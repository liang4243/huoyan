const { getOpenPages, waitForPageReady } = require('./browser');
const { getAdapter } = require('./adapterManager');
const { waitRandom, actionDelayRange } = require('./pacing');
const { moveHomepageMouse } = require('./homepageMouse');

const HOME_URLS = {
  taobao: 'https://www.taobao.com/', jd: 'https://www.jd.com/',
  goofish: 'https://www.goofish.com/', '1688': 'https://www.1688.com/',
  pinduoduo: 'https://mobile.yangkeduo.com/'
};

async function findSearchInput(page, adapter, options = {}) {
  const selectors = options.inShop
    ? ['input[name="keyword"]', 'input[name="keywords"]']
    : [...(adapter.search?.inputSelectors || []), '#q', '#key',
      'input[name="q"]', 'input[name="keyword"]', 'input[name="keywords"]',
      'input[type="search"]', 'input[placeholder*="搜索"]', 'input[placeholder*="搜宝贝"]'];
  let input;
  for (const selector of selectors) {
    const candidates = page.locator(selector);
    for (let i = 0; i < await candidates.count(); i += 1) {
      const candidate = candidates.nth(i);
      if (await candidate.isVisible() && await candidate.isEditable()) {
        input = candidate;
        break;
      }
    }
    if (input) break;
  }
  return input;
}

async function submitKeyword(page, adapter, keyword, options = {}) {
  const input = await findSearchInput(page, adapter, options);
  if (!input) throw new Error('No usable search input on the existing page. Open the search page manually; no new search tab or direct search URL was used.');

  await input.scrollIntoViewIfNeeded();
  await input.fill(keyword);
  // A shop form may target _blank by default. Keep its normal submit handler,
  // but ask the browser to navigate the current tab.
  await input.evaluate((el) => {
    if (el.form) el.form.setAttribute('target', '_self');
  });
  const form = input.locator('xpath=ancestor::form[1]');
  const scoped = form.locator('button[type="submit"], input[type="submit"], button:not([type])');
  let clicked = false;
  for (let i = 0; i < await scoped.count(); i += 1) {
    const button = scoped.nth(i);
    if (!(await button.isVisible()) || !(await button.isEnabled())) continue;
    await button.evaluate((el) => el.removeAttribute('formtarget'));
    await button.click({ timeout: 5000 });
    clicked = true;
    break;
  }
  if (!clicked && !options.inShop) {
    for (const selector of adapter.search?.searchButtonSelectors || []) {
      const button = page.locator(selector).first();
      if (!(await button.isVisible()) || !(await button.isEnabled())) continue;
      await button.click({ timeout: 5000 });
      clicked = true;
      break;
    }
  }
  if (!clicked) await input.press('Enter');
  await waitForPageReady(page);
  const waitMs = await waitRandom(page);
  return { page, adapter, action: clicked ? 'click-search' : 'enter-search', waitMs };
}

async function openStartPage(browser, options, keyword, hooks = {}) {
  if (!options.site || options.site === 'auto') {
    throw new Error('Searching requires an explicit --site.');
  }
  const adapter = getAdapter(options.site);
  if (!adapter) throw new Error(`Unknown site: ${options.site}`);
  const pages = await getOpenPages(browser);
  const target = options.startUrl ? new URL(options.startUrl) : null;
  // Prefer the previous search tab, including after CDP reconnection.
  const key = target
    ? `${adapter.site}:${target.origin}${target.pathname}:${target.searchParams.get('appUid') || ''}`
    : `${adapter.site}:global`;
  const marker = `huoyan-search:v1:${key}`;
  let selected;
  for (const page of pages) {
    try {
      if (await page.evaluate(() => window.name) === marker) {
        selected = { page, adapter };
        break;
      }
    } catch { /* Ignore closed or navigating unrelated tabs. */ }
  }
  const inShop = Boolean(target && target.pathname === '/search.htm');
  // If there is no remembered tab, reuse a matching existing search form.
  // Never repurpose product-detail tabs or a different shop's page.
  if (!selected) {
    for (const page of [...pages].reverse()) {
      try {
        const url = new URL(page.url());
        if (!adapter.match(page.url())) continue;
        if (target) {
          if (url.origin !== target.origin || url.pathname !== target.pathname
            || url.searchParams.get('appUid') !== target.searchParams.get('appUid')) continue;
        } else {
          if (/\/item(?:\.htm)?(?:\/|$)|\/offer\/|\/goods\.html|login|passport/.test(url.pathname + url.hostname)) continue;
          if (adapter.site === 'taobao' && !['www.taobao.com', 's.taobao.com'].includes(url.hostname)) continue;
        }
        if (await findSearchInput(page, adapter, { inShop })) {
          selected = { page, adapter };
          break;
        }
      } catch { /* Skip closed, navigating or unsupported pages. */ }
    }
  }
  const reused = Boolean(selected);
  let entryWaitMs;
  if (!selected) {
    const fs = require('fs-extra');
    const path = require('path');
    const stateFile=path.resolve(__dirname,'../../data/navigation-state.json');
    const state=await fs.pathExists(stateFile)?await fs.readJson(stateFile):{};
    if (adapter.site !== 'taobao' || options.startUrl && options.startUrl !== HOME_URLS.taobao || pages.some(p=>/^https:\/\/[^/]*(?:taobao|tmall)\.com\//.test(p.url())) || state.homeOpened) {
      throw new Error('No reusable search form. Use page controls/back; only the first Taobao homepage entry may use direct navigation.');
    }
    await fs.outputJson(stateFile,{homeOpened:true,openedAt:new Date().toISOString()});
    const url = options.startUrl || HOME_URLS[adapter.site];
    if (!url) throw new Error(`Site ${adapter.site} has no interactive search entry.`);
    const context = browser.contexts()[0] || await browser.newContext();
    const page = pages.find(candidate => !candidate.isClosed() && candidate.url() === 'about:blank') || await context.newPage();
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.evaluate((value) => { window.name = value; }, marker);
    entryWaitMs = await waitRandom(page, 1800, 3500);
    selected = { page, adapter };
  }
  await selected.page.evaluate((value) => { window.name = value; }, marker);
  if (hooks.detectBlockingState) {
    const blocking = await hooks.detectBlockingState(selected.page);
    if (blocking.blocked) throw hooks.createBlockedError(blocking);
  }
  const currentUrl = new URL(selected.page.url());
  let homepageMouse = [];
  if (['/', '/index.html', '/index.htm'].includes(currentUrl.pathname)) {
    homepageMouse = await moveHomepageMouse(selected.page, {
      checkPage: async () => {
        if (!hooks.detectBlockingState) return;
        const blocking = await hooks.detectBlockingState(selected.page);
        if (blocking.blocked) throw hooks.createBlockedError(blocking);
      }
    });
    hooks.log?.('homepage_mouse', { count: homepageMouse.length, moves: homepageMouse });
  }
  const { min, max } = actionDelayRange(options);
  const beforeSearchWaitMs = await waitRandom(selected.page, min, max);
  // Verification can appear during the pause. Check again before submitting.
  if (hooks.detectBlockingState) {
    const blocking = await hooks.detectBlockingState(selected.page);
    if (blocking.blocked) throw hooks.createBlockedError(blocking);
  }
  const result = await submitKeyword(selected.page, adapter, keyword, {
    inShop
  });
  // Reapply after search navigation, including cross-origin transitions.
  await selected.page.evaluate((value) => { window.name = value; }, marker);
  return { ...result, reused, entryWaitMs, beforeSearchWaitMs, homepageMouse };
}

module.exports = { openStartPage, submitKeyword };
