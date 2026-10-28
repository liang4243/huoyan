const path = require('path');
const fs = require('fs-extra');
const crypto = require('crypto');
const { acquireBrowser } = require('./browser');
const { acquireProductPage, rememberProduct, productIdentity, syncTabs } = require('./productTabs');
const { withProductQueue } = require('./productQueue');
const { detectBlockingState, createBlockedError } = require('./collector');
const { inspect } = require('./itemPage');
const { waitRandom } = require('./pacing');

async function composeImages(context, images, caption) {
  const scratch = typeof context.evaluate === 'function' ? context : context.pages().find(p=>!p.isClosed());
  if (!scratch) throw new Error('Collage requires an existing page; no scratch tab will be opened.');
    return await scratch.evaluate(async ({ images, caption }) => {
      const columns = images.length === 1 ? 1 : 2;
      const width = columns * 600;
      const height = 90 + Math.ceil(images.length / columns) * 660;
      const canvas = document.createElement('canvas');
      canvas.width = width; canvas.height = height;
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, width, height);
      ctx.fillStyle = '#222'; ctx.font = '22px sans-serif';
      ctx.fillText(caption.slice(0, 90), 20, 34, width - 40);
      ctx.fillText('Displayed product images; variant-specific content is not guaranteed.', 20, 66, width - 40);
      for (let index = 0; index < images.length; index++) {
        const image = new Image();
        image.src = images[index];
        await image.decode();
        const left = (index % columns) * 600;
        const top = 90 + Math.floor(index / columns) * 660;
        const scale = Math.min(560 / image.width, 600 / image.height);
        const w = image.width * scale, h = image.height * scale;
        ctx.drawImage(image, left + (600 - w) / 2, top + (600 - h) / 2, w, h);
        ctx.fillStyle = '#222'; ctx.font = '20px sans-serif';
        ctx.fillText(`#${index + 1}`, left + 20, top + 638);
      }
      return { base64: canvas.toDataURL('image/png').split(',')[1], width, height };
    }, { images: images.map(buffer => `data:image/png;base64,${buffer.toString('base64')}`), caption });
}

async function selectSkuAndCollage(options) {
  const identity = productIdentity(options.item);
  if (identity.site !== 'taobao') throw new Error('SKU selection currently supports Taobao/Tmall detail pages.');
  const sku = (options.sku || []).map(value => String(value).trim());
  const limit = Math.min(12, Math.max(1, Number.parseInt(options.maxImages, 10) || 8));
  const session = await acquireBrowser({ ...options, browserMode: 'cdp' });
  let page, registry;
  try {
    const selected = await acquireProductPage(session.browser, options.item, options);
    if (!selected.page) throw new Error('Product tab is closed. Cached information can guide selection; use fresh=true only when reopening is needed.');
    ({ page, registry } = selected);
    const check = async () => {
      const blocking = await detectBlockingState(page);
      if (blocking.blocked) throw createBlockedError(blocking);
      if (productIdentity(page.url()).key !== identity.key) throw new Error('SKU navigation changed the product; no unrelated images will be collected.');
    };
    await check();
    const groups = await inspect(page, 'groups');
    if (sku.length !== groups.length) throw new Error(`Supply one exact SKU text for each selectable dimension: ${JSON.stringify(groups)}`);
    // Validate all choices before clicking any option.
    for (let index = 0; index < groups.length; index++) {
      if (!groups[index].options.includes(sku[index])) throw new Error(`Unknown SKU option: ${sku[index]}`);
    }
    const fixed = await inspect(page, 'single-skus');
    if (!fixed.ok) throw new Error(`Fixed SKU is unavailable: ${JSON.stringify(fixed)}`);
    for (let index = 0; index < groups.length; index++) {
      await check();
      const clicked = await inspect(page, 'click-sku', { groupIndex: index, value: sku[index] });
      if (!clicked.clicked) throw new Error(`SKU selection failed: ${JSON.stringify(clicked)}`);
      await waitRandom(page, 500, 1200);
    }
    for (let index = 0; index < groups.length; index++) {
      if (!await inspect(page, 'selected-sku', { groupIndex: index, value: sku[index] })) throw new Error(`SKU selection was not confirmed: ${sku[index]}`);
    }
    if (!await inspect(page, 'all-selected')) throw new Error('SKU combination is incomplete or unavailable.');
    await waitRandom(page);
    await check();
    const images = [], sources = [], seen = new Set(), seenUrls = new Set();
    const capture = async locator => {
      if (images.length >= limit || !await locator.isVisible()) return;
      await locator.scrollIntoViewIfNeeded();
      await locator.evaluate(img => Promise.race([
        img.decode().catch(() => {}), new Promise(resolve => setTimeout(resolve, 5000))
      ]));
      const info = await locator.evaluate(img => ({ src: img.currentSrc || img.src, width: img.naturalWidth, height: img.naturalHeight }));
      if (info.width < 120 || info.height < 120 || seenUrls.has(info.src)) return;
      await check();
      const png = await locator.screenshot({ type: 'png', timeout: 5000 });
      const hash = crypto.createHash('sha256').update(png).digest('hex');
      if (seen.has(hash)) return;
      seen.add(hash); seenUrls.add(info.src); images.push(png); sources.push({ index: images.length, url: info.src, originalWidth: info.width, originalHeight: info.height });
    };
    const initialScroll = await page.evaluate(() => scrollY);
    try {
      const main = page.locator('[data-product-main-image], #J_ImgBooth, .tb-booth img, [class*="mainPic"] img, [class*="MainPic"] img');
      for (let i = 0; i < await main.count(); i++) await capture(main.nth(i));
      const thumbs = page.locator('[data-product-thumbnail], #J_UlThumb li, [class*="thumbnail"] button, [class*="Thumbnail"] button');
      for (let i = 0; i < Math.min(await thumbs.count(), 16) && images.length < limit; i++) {
        const thumb = thumbs.nth(i);
        if (!await thumb.isVisible()) continue;
        await check();
        await thumb.click({ timeout: 5000 });
        await waitRandom(page, 500, 1200);
        await check();
        for (let j = 0; j < await main.count(); j++) await capture(main.nth(j));
      }
      const detail = page.locator('[data-product-image], #description img, #J_DivItemDesc img, [class*="Gallery"] img, [class*="gallery"] img');
      for (let i = 0; i < Math.min(await detail.count(), 40) && images.length < limit; i++) await capture(detail.nth(i));
    } finally { await page.evaluate(top => window.scrollTo(0, top), initialScroll).catch(() => {}); }
    if (!images.length) throw new Error('No loaded product images matched the gallery selectors. No collage was fabricated.');
    await check();
    for (let index = 0; index < groups.length; index++) {
      if (!await inspect(page, 'selected-sku', { groupIndex: index, value: sku[index] })) throw new Error('SKU selection changed while collecting images.');
    }
    const product = await rememberProduct(page, registry, options);
    const collage = await composeImages(page, images, `${product.title} | ${sku.join(' / ')}`);
    const file = path.resolve(options.out || 'data', 'images', 'collages', `${identity.productId}-${Date.now()}-${crypto.randomBytes(3).toString('hex')}.png`);
    await fs.outputFile(file, Buffer.from(collage.base64, 'base64'));
    const metadata = { productId: identity.productId, tabId: product.tabId, url: page.url(), sku,
      imageCount: images.length, sources, file, width: collage.width, height: collage.height,
      observedAt: new Date().toISOString(), warning: 'Rendered gallery/description images, not guaranteed to be exclusive to the selected SKU or full-resolution originals.' };
    await fs.outputJson(file.replace(/\.png$/, '.json'), metadata, { spaces: 2 });
    return { ...metadata, imageBase64: collage.base64, product };
  } finally {
    if (registry) await syncTabs(session.browser, registry, options).catch(() => {});
    await session.browser.close();
  }
}

module.exports = { selectSkuAndCollage: options => withProductQueue(options, () => selectSkuAndCollage(options)), composeImages };
