const { acquireBrowser } = require('./browser');
const { acquireProductPage, rememberProduct, productIdentity, readRegistry } = require('./productTabs');
const { detectBlockingState, createBlockedError } = require('./collector');
const { withProductQueue } = require('./productQueue');

async function inspectProduct(options, hooks = {}) {
  const identity = productIdentity(options.item);
  let session;
  try { session = await acquireBrowser({ ...options, browserMode: 'cdp' }); }
  catch (error) {
    if (!options.fresh) {
      const cached = (await readRegistry(options)).products[identity.key]?.cache;
      if (cached) return { source: 'cache', stale: true, browserUnavailable: true, product: cached };
    }
    throw error;
  }
  try {
    const selected = await acquireProductPage(session.browser, options.item, { ...options,
      checkPage: async page => {
        const blocking = await detectBlockingState(page);
        if (blocking.blocked) throw createBlockedError(blocking);
      }
    });
    if (selected.cache) return { source: 'cache', stale: true, product: selected.cache };
    const blocking = await detectBlockingState(selected.page);
    if (blocking.blocked) throw createBlockedError(blocking);
    if (productIdentity(selected.page.url()).key !== selected.identity.key) throw new Error('Page navigated to a different product.');
    const product = await rememberProduct(selected.page, selected.registry, options);
    hooks.log?.('product_page', { source: selected.source, productId: product.productId, url: product.url, tabId: product.tabId });
    return { source: selected.source, stale: false, refreshed: selected.source === 'refreshed-tab', product };
  } finally { await session.browser.close(); }
}

module.exports = { inspectProduct: (options, hooks) => withProductQueue(options, () => inspectProduct(options, hooks)) };
