function randomInteger(min, max) {
  return min + Math.floor(Math.random() * (max - min + 1));
}

async function waitRandom(page, min = 2500, max = 4500) {
  const ms = randomInteger(min, max);
  await page.waitForTimeout(ms);
  return ms;
}

function actionDelayRange(options = {}) {
  const parse = (value, fallback) => {
    const number = Number.parseInt(value, 10);
    return Number.isFinite(number) ? number : fallback;
  };
  const min = Math.max(0, parse(options.delayMin, 12000));
  const max = Math.max(min, parse(options.delayMax, 25000));
  return { min, max };
}

module.exports = { randomInteger, waitRandom, actionDelayRange };
