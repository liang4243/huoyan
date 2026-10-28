const MODAL_SELECTORS = [
  '.baxia-dialog-close',
  'iframe#baxia-dialog-content',
  '.ant-modal-wrap.login-modal-wrap--Tb8DyHnb',
  '.login-modal-wrap--Tb8DyHnb',
  'iframe#alibaba-login-box'
];

const CLOSE_SELECTORS = [
  '.baxia-dialog-close',
  '.closeIconBg--cubvOqVh',
  '.closeIcon--gwB7wNKs',
  '.closeIcon--jnS6DrX5',
  '.ant-modal-body [class*="closeIconBg"]',
  '.ant-modal-body [class*="closeIcon"]'
];

async function hasLoginPopup(page) {
  for (const selector of MODAL_SELECTORS) {
    try {
      if (await page.locator(selector).first().isVisible({ timeout: 800 })) return true;
    } catch {
      // Keep probing other known popup signatures.
    }
  }
  return false;
}

async function closeLoginPopup(page) {
  for (const selector of CLOSE_SELECTORS) {
    try {
      const locator = page.locator(selector);
      const count = await locator.count();
      for (let index = 0; index < count; index += 1) {
        const target = locator.nth(index);
        if (await target.isVisible({ timeout: 500 })) {
          await target.click({ timeout: 3000 });
          await page.waitForTimeout(800);
          return { action: 'close', ok: true, selector, index };
        }
      }
    } catch {
      // Try the next close selector.
    }
  }

  return { action: 'close', ok: false, reason: 'close button not found' };
}

async function closeAllLoginPopups(page, maxAttempts = 4) {
  const attempts = [];

  for (let index = 0; index < maxAttempts; index += 1) {
    if (!(await hasLoginPopup(page))) break;
    const closeResult = await closeLoginPopup(page);
    attempts.push(closeResult);
    if (!closeResult.ok) break;
    await page.waitForTimeout(800);
  }

  return attempts;
}

async function clickQuickEnter(page) {
  try {
    const quickEnter = page
      .frameLocator('#alibaba-login-box')
      .getByText('\u5feb\u901f\u8fdb\u5165', { exact: true });
    await quickEnter.click({ timeout: 5000 });
    await page.waitForTimeout(2000);
    return { action: 'quick-enter', ok: true };
  } catch (error) {
    return {
      action: 'quick-enter',
      ok: false,
      reason: error && error.message ? error.message.split('\n')[0] : String(error)
    };
  }
}

async function handleLoginPopup(page, mode = 'ignore') {
  if (!mode || mode === 'ignore') return { mode: 'ignore', handled: false };
  if (!(await hasLoginPopup(page))) return { mode, handled: false, reason: 'popup not found' };

  if (mode === 'close') {
    const attempts = await closeAllLoginPopups(page);
    return { mode, handled: attempts.some((attempt) => attempt.ok), attempts };
  }

  if (mode === 'quick-enter') {
    const attempts = [];
    const quickResult = await clickQuickEnter(page);
    attempts.push(quickResult);
    if (quickResult.ok && !(await hasLoginPopup(page))) {
      return { mode, handled: true, attempts };
    }

    attempts.push(...await closeAllLoginPopups(page));
    return { mode, handled: attempts.some((attempt) => attempt.ok), attempts };
  }

  return { mode, handled: false, reason: `unsupported mode: ${mode}` };
}

module.exports = {
  closeAllLoginPopups,
  closeLoginPopup,
  handleLoginPopup,
  hasLoginPopup
};
