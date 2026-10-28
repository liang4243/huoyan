// Write-style item page actions: add to cart / favorite on Taobao item pages.
// Boundary: these are logged-in user actions in the visible page. No order
// submission, no payment, no captcha bypass. Reuses the collector's blocking
// detection and interactive login recovery; Taobao sessions stay visible
// after recovery (baxia re-challenges headless).

const { acquireBrowser } = require('./browser');
const { detectBlockingState } = require('./collector');
const { recoverByInteractiveLogin } = require('./loginRecovery');
const { sleepRandom } = require('./utils');

const { inspect } = require('./itemPage');
const { acquireProductPage, rememberProduct, syncTabs } = require('./productTabs');
const { withProductQueue } = require('./productQueue');
const SITE_STAY_VISIBLE = { taobao: true, tmall: true };

function resolveItemUrl(item) {
  const value = String(item || '').trim();
  if (/^\d+$/.test(value)) return 'https://item.taobao.com/item.htm?id=' + value;
  let url;
  try { url = new URL(value); } catch { throw new Error('Invalid item: expected numeric id or Taobao/Tmall item URL.'); }
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password
    || !['item.taobao.com', 'detail.tmall.com', 'detail.tmall.hk'].includes(url.hostname)
    || url.pathname !== '/item.htm' || !/^\d+$/.test(url.searchParams.get('id') || '')) {
    throw new Error('Only Taobao/Tmall item.htm URLs with a numeric id are supported.');
  }
  url.protocol = 'https:';
  return url.href;
}

function siteOfUrl(url) { return new URL(url).hostname === 'item.taobao.com' ? 'taobao' : 'tmall'; }

const readSkuGroups = (page) => inspect(page, 'groups');
const clickSkuOption = (page, groupIndex, value) => inspect(page, 'click-sku', { groupIndex, value });
const isOptionSelected = (page, groupIndex, value) => inspect(page, 'selected-sku', { groupIndex, value });
const setQuantity = (page, count) => inspect(page, 'set-quantity', { count });
const clickAddToCart = (page) => inspect(page, 'cart');
const clickFavorite = (page) => inspect(page, 'favorite');

async function waitForEvidence(page, operation, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  do {
    const evidence = await inspect(page, operation);
    if (evidence) return evidence;
    await page.waitForTimeout(250);
  } while (Date.now() < deadline);
  return null;
}
const detectCartSuccess = (page) => waitForEvidence(page, 'cart-evidence', 8000);
const detectFavoriteResult = (page) => waitForEvidence(page, 'favorite-evidence', 6000);

async function runItemAction(options, hooks = {}) {
  const log = hooks.log || (() => {});
  const action = options.action;
  if (!['cart', 'fav'].includes(action)) throw new Error(`Unknown action: ${action}`);

  const url = resolveItemUrl(options.item);
  const site = siteOfUrl(url);
  if (site === 'other') throw new Error('Only taobao/tmall item pages are supported for now.');
  const skuValues = (options.sku || []).map((v) => String(v).trim()).filter(Boolean);
  const countText = String(options.count ?? '1');
  const count = Number(countText);
  if (!/^\d+$/.test(countText) || !Number.isSafeInteger(count) || count < 1) {
    throw new Error('Quantity must be a positive integer.');
  }
  const interactiveLogin = options.interactiveLogin !== false;
  const loginTimeoutMs = Math.max(30, Number.parseInt(options.loginTimeout, 10) || 300) * 1000;

  let browserSession = await acquireBrowser({
    ...options,
    cdp: options.cdp || 'http://127.0.0.1:9222',
    browserMode: options.browser || 'cdp',
    debugBrowser: Boolean(options.debugBrowser)
  });
  let browser = browserSession.browser;
  log('browser_ready', { source: browserSession.source, headless: browserSession.headless });

  let result;
  let page;
  let registry;
  try {
    let context = browser.contexts()[0] || await browser.newContext();
    const selected = await acquireProductPage(browser, url, { ...options, requirePage: true });
    page = selected.page;
    registry = selected.registry;
    log('item_tab', { source: selected.source, productId: selected.identity.productId });

    // Login wall / risk-control handling, same contract as the collector.
    let blocking = await detectBlockingState(page);
    if (blocking.blocked) {
      log('blocked', blocking);
      let recovery = null;
      if (interactiveLogin && browserSession.source === 'launch') {
        recovery = await recoverByInteractiveLogin({
          headlessBrowser: browser,
          blockedState: blocking,
          recoverUrl: url,
          userDataDir: browserSession.userDataDir,
          edgePath: options.edgePath,
          chromePath: options.chromePath,
          browserOverrides: {},
          keepVisible: Boolean(SITE_STAY_VISIBLE[site]),
          timeoutMs: loginTimeoutMs,
          detectBlockingState,
          log
        });
      }
      if (!recovery) {
        const error = new Error(`Item action blocked: ${JSON.stringify(blocking)}`);
        error.exitCode = 2;
        throw error;
      }
      browserSession = recovery.browserSession;
      browser = recovery.browserSession.browser;
      context = browser.contexts()[0] || await browser.newContext();
      page = recovery.page;
      blocking = await detectBlockingState(page);
      if (blocking.blocked) {
        const error = new Error(`Still blocked after login recovery: ${JSON.stringify(blocking)}`);
        error.exitCode = 2;
        throw error;
      }
    }

    const finalUrl = new URL(resolveItemUrl(page.url()));
    if (finalUrl.searchParams.get('id') !== new URL(url).searchParams.get('id')) {
      throw new Error('The browser did not reach the requested item.');
    }
    const title = await page.title();
    const snapshot = await rememberProduct(page, registry, options);
    log('item_page', { productId: snapshot.productId, tabId: snapshot.tabId, url: page.url(), title: title.slice(0, 60) });

    if (action === 'cart') {
      const singles = await inspect(page, 'single-skus');
      if (!singles.ok) {
        const error = new Error(`Cannot select fixed SKU: ${JSON.stringify(singles)}`);
        error.exitCode = 3;
        throw error;
      }
      const groups = await readSkuGroups(page);
      if (groups.length > 0 && skuValues.length === 0) {
        const error = new Error(`Item has ${groups.length} SKU dimension(s); pass --sku. ${JSON.stringify(groups)}`);
        error.exitCode = 3;
        error.skuGroups = groups;
        throw error;
      }
      if (skuValues.length !== groups.length) {
        const error = new Error(`Item has ${groups.length} SKU dimension(s) but ${skuValues.length} --sku value(s) given. ${JSON.stringify(groups)}`);
        error.exitCode = 3;
        error.skuGroups = groups;
        throw error;
      }

      for (let gi = 0; gi < groups.length; gi += 1) {
        const click = await clickSkuOption(page, gi, skuValues[gi]);
        log('sku_click', { group: gi, value: skuValues[gi], ...click });
        if (!click.clicked) {
          const error = new Error(`SKU option not found: "${skuValues[gi]}". Available: ${JSON.stringify(click.available)}`);
          error.exitCode = 3;
          error.skuGroups = groups;
          throw error;
        }
        await sleepRandom(500, 1200);
      }
      for (let gi = 0; gi < groups.length; gi += 1) {
        const selected = await isOptionSelected(page, gi, skuValues[gi]);
        if (!selected) {
          const error = new Error(`SKU selection not confirmed: "${skuValues[gi]}".`);
          error.exitCode = 3;
          throw error;
        }
      }

      const qty = await setQuantity(page, count);
      log('quantity', qty);
      if (!qty.set) {
        const error = new Error(`Quantity could not be set: ${JSON.stringify(qty)}`);
        error.exitCode = 3;
        throw error;
      }

      await sleepRandom(400, 900);
      if (await inspect(page, 'quantity') !== String(count) || !await inspect(page, 'all-selected')) {
        const error = new Error('Quantity or SKU state changed before adding to cart.');
        error.exitCode = 3;
        throw error;
      }
      const beforeClick = await detectBlockingState(page);
      if (beforeClick.blocked) {
        const error = new Error('Item action blocked before adding to cart.');
        error.exitCode = 2;
        throw error;
      }
      await inspect(page, 'snapshot', { action: 'cart' });
      const click = await clickAddToCart(page);
      log('cart_click', click);
      if (!click.clicked) {
        const error = new Error('Add-to-cart button not found on the page.');
        error.exitCode = 4;
        throw error;
      }
      const evidence = await detectCartSuccess(page);
      result = {
        action, ok: Boolean(evidence), evidence: evidence || 'no-success-indicator',
        item: options.item, sku: skuValues, count, url: page.url(), title: title.slice(0, 80)
      };
    } else {
      await inspect(page, 'snapshot', { action: 'fav' });
      const click = await clickFavorite(page);
      log('fav_click', click);
      if (click.already) {
        result = { action, ok: true, evidence: 'already-favorited', item: options.item, url: page.url(), title: title.slice(0, 80) };
      } else if (!click.clicked) {
        const error = new Error(`Favorite button not found: ${click.reason || ''}`);
        error.exitCode = 4;
        throw error;
      } else {
        const evidence = await detectFavoriteResult(page);
        result = {
          action, ok: Boolean(evidence), evidence: evidence || 'no-success-indicator',
          item: options.item, url: page.url(), title: title.slice(0, 80)
        };
      }
    }

    return result;
  } finally {
    // Keep CDP product tabs alive; refresh their mapping/cache after actions.
    if (page && registry) {
      try {
        await syncTabs(browser, registry, options);
        if (!(await detectBlockingState(page)).blocked) await rememberProduct(page, registry, options);
      } catch { /* A user may have closed or navigated the tab. */ }
    }
    try {
      await browser.close();
    } catch {
      // The visible recovery window is user-owned after stay-visible recovery.
    }
  }
}

module.exports = { runItemAction: (options, hooks) => withProductQueue(options, () => runItemAction(options, hooks)), resolveItemUrl, readSkuGroups };
