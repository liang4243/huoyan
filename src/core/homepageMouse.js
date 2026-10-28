const { randomInteger, waitRandom } = require('./pacing');

async function moveHomepageMouse(page, hooks = {}) {
  const { width, height } = await page.evaluate(() => ({ width: innerWidth, height: innerHeight }));
  if (width < 80 || height < 80) return [];
  await hooks.checkPage?.();
  await page.bringToFront();
  const margin = 24;
  let current = { x: randomInteger(Math.round(width * 0.35), Math.round(width * 0.65)),
    y: randomInteger(Math.round(height * 0.35), Math.round(height * 0.65)) };
  await page.mouse.move(current.x, current.y, { steps: 3 });
  const directions = ['up', 'down', 'left', 'right'];
  for (let i = directions.length - 1; i > 0; i--) {
    const j = randomInteger(0, i);
    [directions[i], directions[j]] = [directions[j], directions[i]];
  }
  const count = randomInteger(4, 7);
  while (directions.length < count) directions.push(['up', 'down', 'left', 'right'][randomInteger(0, 3)]);
  const moves = [];
  for (let direction of directions) {
    await hooks.checkPage?.();
    const horizontal = direction === 'left' || direction === 'right';
    const axis = horizontal ? 'x' : 'y';
    const extent = horizontal ? width : height;
    const distance = Math.round(extent * randomInteger(8, 25) / 100);
    const sign = direction === 'left' || direction === 'up' ? -1 : 1;
    const target = { ...current, [axis]: Math.max(margin, Math.min(extent - margin, current[axis] + sign * distance)) };
    if (Math.abs(target[axis] - current[axis]) < 5) {
      target[axis] = Math.max(margin, Math.min(extent - margin, current[axis] - sign * distance));
      direction = { up: 'down', down: 'up', left: 'right', right: 'left' }[direction];
    }
    const steps = randomInteger(6, 12);
    const durationMs = randomInteger(250, 650);
    const from = current;
    for (let step = 1; step <= steps; step++) {
      await page.mouse.move(from.x + (target.x - from.x) * step / steps,
        from.y + (target.y - from.y) * step / steps);
      await page.waitForTimeout(durationMs / steps);
    }
    const pauseMs = await waitRandom(page, 350, 1200);
    moves.push({ direction, from, to: target, durationMs, pauseMs });
    current = target;
  }
  await hooks.checkPage?.();
  return moves;
}

module.exports = { moveHomepageMouse };
