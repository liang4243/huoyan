const path = require('path');
const fs = require('fs-extra');
const { acquireBrowser, getOpenPages, scrollPage, waitForPageReady } = require('./browser');
const { getAdapter, selectPageForSite } = require('./adapterManager');
const { assignIds } = require('./normalize');
const { applyRules } = require('./rules');
const { exportItems } = require('./exporter');
const { buildSearchUrl } = require('./searchUrls');
const { handleLoginPopup } = require('./loginPopup');
const { recoverByInteractiveLogin, waitForManualClear } = require('./loginRecovery');
const { clickNextPageButton, clickSearchButton } = require('./searchActions');
const { openStartPage } = require('./searchPage');
const { actionDelayRange } = require('./pacing');
const { dedupeItems, isoNow, sleepRandom, timestampForFile } = require('./utils');

function parseInteger(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseNumber(value) {
  if (value == null || value === '') return undefined;
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function getDedupeKey(item) {
  return item.url
    ? `url:${item.url}`
    : `fallback:${item.title}|${item.price}|${item.seller}`;
}

function createBlockedError(blockingState) {
  const error = new Error(`Collection blocked: ${JSON.stringify(blockingState)}`);
  error.exitCode = 2;
  error.blockingState = blockingState;
  return error;
}

async function handlePopupAndSearch(page, adapter, mode, labelPrefix, log) {
  const popupResult = await handleLoginPopup(page, mode);
  if (popupResult.mode !== 'ignore') {
    log(labelPrefix, popupResult);
  }

  if (!popupResult.handled) return popupResult;

  const searchResult = await clickSearchButton(page, adapter);
  log(`${labelPrefix}_search`, searchResult);

  const popupAfterSearchResult = await handleLoginPopup(page, mode);
  if (popupAfterSearchResult.mode !== 'ignore') {
    log(`${labelPrefix}_after_search`, popupAfterSearchResult);
  }

  return popupResult;
}

async function findCardsWithRetry(adapter, page, attempts = 3) {
  let lastError;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await adapter.findCards(page);
    } catch (error) {
      lastError = error;
      const message = String(error && error.message ? error.message : error);
      if (!/Execution context was destroyed|navigation|Target closed/i.test(message)) {
        throw error;
      }
      await waitForPageReady(page);
      await page.waitForTimeout(1500);
    }
  }
  throw lastError;
}

function parseDelayRange(options) {
  return actionDelayRange(options);
}

async function politeDelay(options, reason, log) {
  const { min, max } = parseDelayRange(options);
  if (max <= 0) return 0;
  const delay = await sleepRandom(min, max);
  log('delay', { reason, ms: delay });
  return delay;
}

async function detectBlockingState(page) {
  const url = page.url();
  if (/passport\.jd\.com|risk_handler|login\.taobao\.com|login\.tmall\.com|login\.1688\.com|passport\.meituan\.com|yangkeduo\.com\/login/i.test(url)) {
    return { blocked: true, reason: 'login-page', url };
  }

  try {
    const result = await page.evaluate(() => {
      const text = (document.body?.innerText || document.body?.textContent || '').slice(0, 5000);
      const hasVerifyText = /\u9a8c\u8bc1\u7801|\u5b89\u5168\u9a8c\u8bc1|\u4eba\u673a\u9a8c\u8bc1|\u6ed1\u5757\u9a8c\u8bc1|\u8bf7\u767b\u5f55/.test(text);
      // A passed challenge can leave its baxia/captcha node in the DOM while
      // hidden; only mounted-and-visible nodes count as blocking.
      const isNodeVisible = (node) => {
        if (!node) return false;
        const rect = node.getBoundingClientRect();
        const style = window.getComputedStyle(node);
        return rect.width > 1 && rect.height > 1
          && style.display !== 'none' && style.visibility !== 'hidden';
      };
      const verifyNodes = document.querySelectorAll(
        'iframe[src*="captcha"], iframe[src*="baxia"], [class*="captcha"], [id*="captcha"], [class*="verify"], [id*="verify"]'
      );
      const hasVerifyNode = Array.from(verifyNodes).some(isNodeVisible);
      return { hasVerifyText, hasVerifyNode };
    });

    if (result.hasVerifyText || result.hasVerifyNode) {
      return { blocked: true, reason: 'verification-detected', url };
    }
  } catch {
    // If the page is navigating or inaccessible, continue and let extraction retries handle it.
  }

  return { blocked: false, url };
}

async function collect(options, hooks = {}) {
  const log = hooks.log || (() => {});
  const max = Math.max(1, parseInteger(options.max, 50));
  const pageLimit = Math.max(1, parseInteger(options.pages, 1));
  const scroll = options.scroll == null || options.scroll === 'auto'
    ? 'auto' : Math.max(0, parseInteger(options.scroll, 0));
  const cdp = options.cdp || 'http://127.0.0.1:9222';
  const keyword = options.keyword || '';
  const loginPopupMode = options.loginPopup || 'ignore';
  const stopOnVerify = options.stopOnVerify !== false;
  const failOnBlocked = options.failOnBlocked !== false;
  const interactiveLogin = options.interactiveLogin !== false;
  const loginTimeoutMs = Math.max(30, parseInteger(options.loginTimeout, 300)) * 1000;
  const loginRecoveryLimit = 2;
  const extractTime = isoNow();
  const timestamp = timestampForFile();
  const outDir = path.resolve(process.cwd(), options.out || 'data');

  if (!keyword) throw new Error('Missing --keyword.');

  await fs.ensureDir(path.join(outDir, 'raw'));
  await fs.ensureDir(path.join(outDir, 'reports'));
  await fs.ensureDir(path.join(outDir, 'images'));

  // Adapter-level browser preferences (user agent / mobile viewport for
  // app-first sites like Pinduoduo) must be known before launch. They only
  // apply when the site is explicit; auto detection works on the desktop UA.
  const preferredAdapter = options.site && options.site !== 'auto'
    ? getAdapter(options.site)
    : null;
  const browserOverrides = (preferredAdapter && preferredAdapter.browser) || {};

  let browserSession = await acquireBrowser({
    ...options,
    ...browserOverrides,
    cdp,
    browserMode: options.browser || options.browserMode || 'cdp',
    debugBrowser: Boolean(options.debugBrowser)
  });
  let browser = browserSession.browser;
  log('browser_ready', {
    source: browserSession.source,
    cdpEndpoint: browserSession.cdpEndpoint,
    headless: browserSession.headless,
    executablePath: browserSession.executablePath,
    userDataDir: browserSession.userDataDir
  });

  try {
    let searchSelection;
    if (options.startUrl || options.openSearch) {
      searchSelection = await openStartPage(browser, options, keyword, { detectBlockingState, createBlockedError, log });
      log('search_page', { action: searchSelection.action, reused: searchSelection.reused, beforeSearchWaitMs: searchSelection.beforeSearchWaitMs, waitMs: searchSelection.waitMs, entryWaitMs: searchSelection.entryWaitMs, url: searchSelection.page.url() });
    }

    const pages = await getOpenPages(browser);
    const selected = searchSelection || await selectPageForSite(pages, options.site || 'auto');
    if (!selected) {
      const launchHint = browserSession.source === 'launch'
        ? 'When launching a fresh browser, use --open-search with an explicit --site so HuoYan has a result page to collect.'
        : 'Confirm Edge was started with --remote-debugging-port=9222 and the target results page is open.';
      throw new Error(`No open page matched site ${options.site || 'auto'}. ${launchHint}`);
    }

    const { adapter } = selected;
    let page = selected.page;
    await waitForPageReady(page);
    const firstPopupResult = await handlePopupAndSearch(page, adapter, loginPopupMode, 'login_popup', log);

    const normalizedItems = [];
    const seenItems = new Set();
    let blocked = null;
    let loginRecoveries = 0;

    for (let currentPage = 1; currentPage <= pageLimit && normalizedItems.length < max; currentPage += 1) {
      if (stopOnVerify) {
        const blockingState = await detectBlockingState(page);
        if (blockingState.blocked) {
          blocked = blockingState;
          log('blocked', blockingState);

          // Already collecting visibly (stay-visible mode): the user clears
          // the challenge in the window they are looking at. Restarting the
          // browser here resets the session and re-triggers the challenge.
          if (interactiveLogin && browserSession.source === 'launch' && browserSession.headless === false) {
            const cleared = await waitForManualClear({
              page,
              timeoutMs: loginTimeoutMs,
              detectBlockingState,
              log
            });
            if (cleared) {
              blocked = null;
            } else if (failOnBlocked) {
              throw createBlockedError(blockingState);
            } else {
              break;
            }
          } else {
            let recovery = null;
            if (interactiveLogin && browserSession.source === 'launch' && loginRecoveries < loginRecoveryLimit) {
              loginRecoveries += 1;
              recovery = await recoverByInteractiveLogin({
                headlessBrowser: browser,
                blockedState: blockingState,
                recoverUrl: buildSearchUrl(adapter, keyword) || blockingState.url,
                userDataDir: browserSession.userDataDir,
                edgePath: options.edgePath,
                chromePath: options.chromePath,
                browserOverrides,
                // Alibaba-style risk control (baxia) re-challenges headless
                // sessions even with a valid login, so keep collecting in the
                // visible window after the first headless resume got blocked.
                keepVisible: Boolean(adapter.stayVisibleAfterRecovery) || loginRecoveries >= 2,
                timeoutMs: loginTimeoutMs,
                detectBlockingState,
                log
              });
            }

            if (!recovery) {
              if (failOnBlocked) throw createBlockedError(blockingState);
              break;
            }

            browserSession = recovery.browserSession;
            browser = recovery.browserSession.browser;
            page = recovery.page;
            currentPage -= 1;
            continue;
          }
        }
      }

      if (scroll === 'auto' || scroll > 0) {
        const scrolling = await scrollPage(page, scroll);
        log('page_scroll', { page: currentPage, ...scrolling });
        if (stopOnVerify) {
          const state = await detectBlockingState(page);
          if (state.blocked) {
            log('blocked', state);
            if (failOnBlocked) throw createBlockedError(state);
            blocked = state;
            break;
          }
        }
      }
      const pageUrl = page.url();
      let cards = await findCardsWithRetry(adapter, page);
      if (cards.length === 0 && firstPopupResult.handled) {
        const retrySearchResult = await clickSearchButton(page, adapter);
        log('search_retry', retrySearchResult);
        const retryPopupResult = await handleLoginPopup(page, loginPopupMode);
        if (retryPopupResult.mode !== 'ignore') {
          log('login_popup_after_retry', retryPopupResult);
        }
        cards = await findCardsWithRetry(adapter, page);
      }

      log('page_collect', { page: currentPage, url: pageUrl, cards: cards.length });

      for (const card of cards) {
        if (normalizedItems.length >= max) break;
        try {
          const rawItem = await adapter.extractFromCard(card, page);
          const item = adapter.normalize(rawItem, {
            keyword,
            pageUrl,
            extractTime
          });
          if (!item) continue;

          const key = getDedupeKey(item);
          if (seenItems.has(key)) continue;

          seenItems.add(key);
          normalizedItems.push(item);
        } catch {
          // Page structures can change frequently. Skip bad cards and continue.
        }
      }

      if (currentPage >= pageLimit || normalizedItems.length >= max) break;

      await politeDelay(options, 'before-next-page', log);
      const nextPageResult = await clickNextPageButton(page, adapter);
      log('page_next', { fromPage: currentPage, ...nextPageResult });
      if (!nextPageResult.ok) break;

      await waitForPageReady(page);
      await politeDelay(options, 'after-next-page', log);
      const nextPopupResult = await handleLoginPopup(page, loginPopupMode);
      if (nextPopupResult.mode !== 'ignore') {
        log('login_popup_after_next', nextPopupResult);
      }
    }

    const deduped = dedupeItems(normalizedItems).slice(0, max);
    const ruled = deduped.map((item) => applyRules(item, {
      referencePrice: parseNumber(options.referencePrice)
    }));
    const dated = timestamp.slice(0, 8);
    const items = assignIds(ruled, adapter.site, dated);
    const outputs = await exportItems(items, {
      site: adapter.site,
      keyword,
      timestamp,
      extractTime,
      outDir,
      format: options.format || 'jsonl,md'
    });

    return {
      site: adapter.site,
      page: page.url(),
      items,
      itemCount: items.length,
      outputs,
      blocked,
      warning: items.length === 0 && adapter.site === 'jd' && /passport\.jd\.com/i.test(page.url())
        ? 'jd redirected to login page. Open the JD search result page in a logged-in Edge started with --remote-debugging-port, then run collect without forcing a fresh unauthenticated profile.'
        : ''
    };
  } finally {
    try {
      await browser.close();
    } catch {
      // The browser may already be closed by the interactive login recovery.
    }
  }
}

module.exports = {
  collect,
  createBlockedError,
  detectBlockingState,
  parseInteger,
  parseNumber
};
