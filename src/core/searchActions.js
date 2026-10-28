const { waitRandom } = require('./pacing');
function readSearchConfig(adapterOrSite) {
  return typeof adapterOrSite === 'object' && adapterOrSite
    ? adapterOrSite.search || {}
    : {};
}

async function clickSearchButton(page, adapterOrSite) {
  const searchConfig = readSearchConfig(adapterOrSite);
  const selectors = searchConfig.searchButtonSelectors || ['form button[type="submit"]', 'button[type="submit"]'];

  for (const selector of selectors) {
    try {
      const locator = page.locator(selector).first();
      if (await locator.isVisible({ timeout: 1000 })) {
        await locator.click({ timeout: 5000 });
        await waitRandom(page);
        return { action: 'click-search', ok: true, selector };
      }
    } catch {
      // Try the next search selector.
    }
  }

  try {
    const submitted = await page.evaluate(() => {
      const form = document.querySelector('form');
      if (!form) return false;
      if (typeof form.requestSubmit === 'function') form.requestSubmit();
      else form.submit();
      return true;
    });
    if (submitted) {
      await waitRandom(page);
      return { action: 'submit-search-form', ok: true };
    }
  } catch {
    // Fall through to failure result.
  }

  return { action: 'click-search', ok: false, reason: 'search button not found' };
}

async function clickNextPageButton(page, adapterOrSite) {
  const searchConfig = readSearchConfig(adapterOrSite);
  const selectors = searchConfig.nextButtonSelectors || ['a[rel="next"]', '.next', '[class*="next"]'];

  for (const selector of selectors) {
    try {
      const locator = page.locator(selector);
      const count = await locator.count();
      for (let index = count - 1; index >= 0; index -= 1) {
        const target = locator.nth(index);
        if (!(await target.isVisible({ timeout: 500 }))) continue;

        const disabled = await target.evaluate((el) => {
          const className = String(el.className || '');
          return Boolean(
            el.disabled
            || el.getAttribute('aria-disabled') === 'true'
            || className.includes('disabled')
            || className.includes('disable')
          );
        });
        if (disabled) continue;

        await target.click({ timeout: 5000 });
        await waitRandom(page);
        return { action: 'click-next-page', ok: true, selector, index };
      }
    } catch {
      // Try the next selector.
    }
  }

  try {
    const clicked = await page.evaluate(() => {
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0
          && style.display !== 'none'
          && style.visibility !== 'hidden';
      };
      const disabled = (el) => {
        const className = String(el.className || '');
        return Boolean(
          el.disabled
          || el.getAttribute('aria-disabled') === 'true'
          || className.includes('disabled')
          || className.includes('disable')
        );
      };
      const textOf = (el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
      const candidates = Array.from(document.querySelectorAll('button, a, div[role="button"], span[role="button"]'))
        .filter((el) => visible(el) && !disabled(el))
        .filter((el) => {
          const label = [
            textOf(el),
            el.getAttribute('aria-label'),
            el.getAttribute('title'),
            el.className,
            el.id
          ].filter(Boolean).join(' ');
          const lower = label.toLowerCase();
          return label.includes('\u4e0b\u4e00\u9875')
            || lower.includes('next')
            || lower.includes('right')
            || lower.includes('arrow-right')
            || label.includes('>')
            || label.includes('\u203a');
        });

      const target = candidates[candidates.length - 1];
      if (!target) return false;
      target.click();
      return true;
    });
    if (clicked) {
      await waitRandom(page);
      return { action: 'click-next-page-fallback', ok: true };
    }
  } catch {
    // Fall through to failure result.
  }

  return { action: 'click-next-page', ok: false, reason: 'next page button not found' };
}

module.exports = {
  clickNextPageButton,
  clickSearchButton
};
