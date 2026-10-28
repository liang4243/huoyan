const { normalizeItem } = require('../core/normalize');

const site = 'goofish';

const search = {
  buildUrl(keyword) {
    return `https://www.goofish.com/search?q=${encodeURIComponent(keyword || '')}`;
  },
  searchButtonSelectors: [
    'button.search-icon--bewLHteU',
    'form button[type="submit"]'
  ],
  nextButtonSelectors: [
    'button[class*="search-page-tiny-arrow-container"]:has([class*="search-page-tiny-arrow-right"])',
    'button[class*="page"][class*="next"]',
    '.ant-pagination-next button',
    '.ant-pagination-next'
  ]
};

function match(url) {
  return /(^|\.)goofish\.com/i.test(url) || /(^|\.)2\.taobao\.com/i.test(url);
}

async function findCards(page) {
  const selectors = [
    'a[href*="/item"]',
    'a[href*="goofish.com/item"]',
    '[class*="feeds-item"]',
    '[class*="item-card"]',
    '[class*="goods-card"]',
    '[class*="card"]'
  ];

  const handles = await page.$$(selectors.join(','));
  const cards = [];

  for (const handle of handles.slice(0, 400)) {
    try {
      const ok = await handle.evaluate((el) => {
        const text = (el.innerText || el.textContent || '').trim();
        const href = el.matches('a[href]') ? el.href : el.querySelector('a[href]')?.href;
        return Boolean(href) && /[¥￥]\s*\d|\d+(?:\.\d+)?\s*元/.test(text);
      });
      if (ok) cards.push(handle);
    } catch {
      // Ignore detached or inaccessible nodes.
    }
  }

  return cards;
}

async function extractFromCard(card) {
  return card.evaluate((el) => {
    const textOf = (selector) => {
      const node = el.querySelector(selector);
      return (node?.innerText || node?.textContent || '').trim();
    };
    const attrOf = (selector, attr) => {
      const node = el.querySelector(selector);
      return node?.getAttribute(attr) || '';
    };
    const lines = Array.from(new Set((el.innerText || el.textContent || '')
      .split(/\n+/)
      .map((line) => line.trim())
      .filter(Boolean)));
    const fullText = lines.join(' ');
    const anchor = el.matches('a[href]') ? el : el.querySelector('a[href*="/item"],a[href*="goofish.com/item"],a[href]');
    const image = el.querySelector('img');
    const priceRaw = (textOf('[class*="price"]')
      || textOf('[class*="Price"]')
      || (fullText.match(/[¥￥]\s*\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s*元/) || [])[0]
      || '').replace(/\s+/g, '');
    const title = textOf('[class*="title"]')
      || textOf('[class*="Title"]')
      || textOf('[class*="name"]')
      || anchor?.getAttribute('title')
      || image?.getAttribute('alt')
      || lines.find((line) => line !== priceRaw && !/[¥￥]\s*\d|\d+(?:\.\d+)?\s*元/.test(line))
      || '';
    const desc = textOf('[class*="desc"]')
      || textOf('[class*="Desc"]')
      || lines.filter((line) => line !== title && line !== priceRaw).slice(0, 3).join(' ');
    const seller = textOf('[class*="seller"]')
      || textOf('[class*="Seller"]')
      || textOf('[class*="user"]')
      || textOf('[class*="nick"]');
    const location = textOf('[class*="location"]')
      || textOf('[class*="Location"]')
      || textOf('[class*="area"]')
      || textOf('[class*="Area"]');

    return {
      title,
      price_raw: priceRaw,
      desc,
      seller,
      location,
      url: anchor?.href || '',
      image_url: image?.currentSrc || image?.src || image?.getAttribute('data-src') || image?.getAttribute('data-lazy') || ''
    };
  });
}

function normalize(rawItem, context) {
  return normalizeItem({ ...rawItem, site }, { ...context, site });
}

module.exports = {
  site,
  search,
  match,
  findCards,
  extractFromCard,
  normalize
};
