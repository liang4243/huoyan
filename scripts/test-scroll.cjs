const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { getDefaultEdgePath, scrollPage } = require('../src/core/browser');

(async () => {
  const browser = await chromium.launch({ executablePath: getDefaultEdgePath(), headless: true });
  const originalRandom = Math.random;
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 800 } });
    page.waitForTimeout = async () => {};
    await page.setContent('<!doctype html><body style="margin:0;height:3000px">PLA fixture</body>');
    Math.random = () => 0.99999999;
    const bottom = await scrollPage(page);
    assert.equal(bottom.plannedCount, 5);
    assert.equal(bottom.count, 2);
    assert.equal(bottom.reachedBottom, true);
    assert.deepEqual(bottom.steps.map(step => step.direction), ['down', 'down', 'up']);
    assert(bottom.steps[1].to >= 2198);
    assert(bottom.steps[2].to < bottom.steps[1].to);
    assert(bottom.steps[2].to > 0);
    assert(bottom.steps.every(step => step.from !== step.to));
    console.log('PASS bottom stops downward movement early, then reverses a little; no empty scrolls');

    await page.setContent('<!doctype html><body style="margin:0;height:20000px">Tall fixture</body>');
    await page.evaluate(() => window.scrollTo(0, 0));
    Math.random = () => 0;
    const low = await scrollPage(page);
    assert.equal(low.plannedCount, 2);
    assert.equal(low.count, 2);
    assert.equal(low.reachedBottom, false);
    assert(low.steps.every(step => step.direction === 'down' && step.screenPercent === 50));
    assert.notEqual(low.steps[0].to, low.steps[1].to);
    console.log('PASS random count reaches lower bound, with different stopping positions before bottom');

    const before = await page.evaluate(() => window.scrollY);
    const disabled = await scrollPage(page, 0);
    assert.deepEqual(disabled.steps, []);
    assert.equal(await page.evaluate(() => window.scrollY), before);
    await page.setContent('<body style="margin:0;height:50px">Short fixture</body>');
    assert.deepEqual((await scrollPage(page)).steps, []);
    console.log('PASS disabled and non-scrollable pages do not scroll');
  } finally {
    Math.random = originalRandom;
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
