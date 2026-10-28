const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const { getDefaultEdgePath } = require('../src/core/browser');
const { moveHomepageMouse } = require('../src/core/homepageMouse');

(async () => {
  const browser = await chromium.launch({ executablePath: getDefaultEdgePath(), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1000, height: 800 } });
    await page.setContent('<!doctype html><body><a href="https://example.invalid">fixture</a><script>window.points=[];window.clicks=0;document.addEventListener("mousemove",e=>points.push([e.clientX,e.clientY]));document.addEventListener("click",()=>clicks++);</script></body>');
    const waits = [];
    page.waitForTimeout = async ms => waits.push(ms);
    const moves = await moveHomepageMouse(page);
    assert(moves.length >= 4 && moves.length <= 7);
    assert.deepEqual([...new Set(moves.slice(0, 4).map(move => move.direction))].sort(), ['down', 'left', 'right', 'up']);
    assert(moves.every(move => move.to.x >= 24 && move.to.x <= 976 && move.to.y >= 24 && move.to.y <= 776));
    assert(moves.every(move => move.durationMs >= 250 && move.durationMs <= 650 && move.pauseMs >= 350 && move.pauseMs <= 1200));
    assert(waits.length > moves.length);
    const events = await page.evaluate(() => ({ points: window.points, clicks: window.clicks }));
    assert(events.points.length > moves.length);
    assert.equal(events.clicks, 0);
    console.log('PASS varied mouse movements in all four directions, bounded positions and random pauses, with no clicks');
    await assert.rejects(moveHomepageMouse(page, { checkPage: async () => { throw new Error('blocked'); } }), /blocked/);
    console.log('PASS verification stops the movement sequence');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
