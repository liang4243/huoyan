const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const { chromium } = require('playwright');
const browserModule = require('../src/core/browser');

(async () => {
  const out = fs.mkdtempSync(path.join(os.tmpdir(), 'huoyan-sku-collage-'));
  const browser = await chromium.launch({ executablePath: browserModule.getDefaultEdgePath(), headless: true, args: ['--no-proxy-server'] });
  try {
    const context = await browser.newContext();
    const html = `<!doctype html><title>PLA耗材</title><body>
      <div data-product-description>PLA 1.75mm，0.5kg/1kg，适合日常打印。</div>
      <div class="skuItem"><span class="label">重量</span><li onclick="select(this)">0.5kg</li><li onclick="select(this)">1kg</li><li class="disabled">缺货</li></div>
      <img data-product-main-image width="200" height="200">
      <button data-product-thumbnail onclick="main.src=pics[2]">图2</button>
      <button data-product-thumbnail onclick="main.src=pics[3]">图3</button>
      <img data-product-image width="200" height="200">
      <button onclick="window.cart++">加入购物车</button><script>
      window.cart=0;window.pics=['red','green','blue','yellow'].map(color=>{const c=document.createElement('canvas');c.width=c.height=200;const x=c.getContext('2d');x.fillStyle=color;x.fillRect(0,0,200,200);return c.toDataURL()});
      window.main=document.querySelector('[data-product-main-image]');main.src=pics[0];document.querySelector('[data-product-image]').src=pics[2];
      window.select=el=>{document.querySelectorAll('.skuItem li').forEach(x=>x.classList.remove('selected'));el.classList.add('selected');main.src=pics[el.innerText==='1kg'?1:0]};</script>`;
    await context.route('**/*', route => route.fulfill({ contentType: 'text/html; charset=utf-8', body: html }));
    const page = await context.newPage();
    await page.goto('https://item.taobao.com/item.htm?id=123');
    page.waitForTimeout = async () => {};
    const originalAcquire = browserModule.acquireBrowser;
    browserModule.acquireBrowser = async () => ({ source: 'cdp', browser: { contexts: () => [context], close: async () => {} } });
    const { inspectProduct } = require('../src/core/productResearch');
    const { selectSkuAndCollage } = require('../src/core/skuCollage');
    try {
      const description = await inspectProduct({ item: '123', out });
      assert(description.product.description.includes('1.75mm'));
      assert(description.product.skuCandidates[0].options.some(option => option.text === '1kg' && !option.disabled));
      assert(description.product.skuCandidates[0].options.some(option => option.text === '缺货' && option.disabled));
      await assert.rejects(selectSkuAndCollage({ item: '123', out, sku: ['不存在'] }), /Unknown SKU/);
      const result = await selectSkuAndCollage({ item: '123', out, sku: ['1kg'] });
      assert.equal(result.imageCount, 3);
      assert.equal(result.width, 1200);
      assert(fs.existsSync(result.file));
      assert(Buffer.from(result.imageBase64, 'base64').subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10])));
      assert.equal(await page.locator('.selected').innerText(), '1kg');
      assert.equal(await page.evaluate(() => window.cart), 0);
      assert.equal(context.pages().length, 1);
      assert.equal(result.tabId, description.product.tabId);
      if (process.argv[2]) fs.copyFileSync(result.file, process.argv[2]);
      console.log('PASS description and SKU candidates -> exact SKU selection -> deduplicated collage; original tab kept, no cart click');
    } finally { browserModule.acquireBrowser = originalAcquire; }
  } finally { await browser.close(); fs.rmSync(out, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
