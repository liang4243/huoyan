const { getOpenPages, waitForPageReady } = require('./browser');

const POLL_INTERVAL_MS = 2000;
// One poll can land mid-navigation, where detectBlockingState reports "not
// blocked" because the DOM check failed. Require two consecutive clear reads.
const CLEAR_STREAK_REQUIRED = 2;

async function hasVisiblePage(browser) {
  try {
    const pages = await getOpenPages(browser);
    return pages.some((page) => {
      const url = page.url() || '';
      return url && url !== 'about:blank' && !url.startsWith('chrome://') && !url.startsWith('edge://');
    });
  } catch {
    return false;
  }
}

/** Strict in-page navigation never restarts a browser or reopens a recovery URL. */
async function recoverByInteractiveLogin({ log }) {
  log?.('login_recovery_disabled', { reason: 'Handle verification in the existing tab; direct recovery navigation is forbidden.' });
  return null;
}

/**
 * Wait for the user to clear a login/verification challenge on the page they
 * are already looking at (visible-window collection). No browser restart:
 * restarting would reset the session and immediately re-trigger the
 * challenge (observed with Taobao baxia). Returns true once clear.
 */
async function waitForManualClear({ page, timeoutMs, detectBlockingState, log }) {
  log('manual_clear_waiting', { timeoutMs });
  const startedAt = Date.now();
  let clearStreak = 0;

  while (Date.now() - startedAt < timeoutMs) {
    let state;
    try {
      state = await detectBlockingState(page);
    } catch {
      state = { blocked: true };
    }
    clearStreak = state.blocked ? 0 : clearStreak + 1;
    if (clearStreak >= CLEAR_STREAK_REQUIRED) {
      log('manual_clear_cleared', { url: page.url() });
      return true;
    }
    await page.waitForTimeout(POLL_INTERVAL_MS).catch(() => {});
  }

  log('manual_clear_failed', { elapsedMs: Date.now() - startedAt });
  return false;
}

module.exports = { recoverByInteractiveLogin, waitForManualClear };
