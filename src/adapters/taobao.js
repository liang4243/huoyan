const { normalizeItem } = require('../core/normalize');

const site = 'taobao';

// Taobao baxia risk control re-challenges headless sessions even when logged
// in, so after interactive recovery the collection keeps running visibly.
const stayVisibleAfterRecovery = true;

const search = {
  buildUrl(keyword) {
    const query = encodeURIComponent(keyword || '');
    return `https://s.taobao.com/search?q=${query}&tab=all`;
  },
  searchButtonSelectors: [
    '#J_Search button',
    '#J_SearchForm button',
    'button[type="submit"]',
    '[class*="search"] button',
    '[class*="Search"] button',
    'form button'
  ],
  nextButtonSelectors: [
    'li.next a',
    'button.next',
    '.pagination-next',
    '[class*="next"]',
    'a[aria-label*="next" i]',
    'button[aria-label*="next" i]',
    'a[title*="下一页"]',
    'button[title*="下一页"]'
  ]
};

function match(url) {
  return /(^|\.)taobao\.com/i.test(url);
}

async function findCards(page) {
  const selectors = [
    '[data-nid]',
    '[data-itemid]',
    '[data-item-id]',
    'a[href*="item.taobao.com/item.htm"]',
    'a[href*="detail.tmall.com/item.htm"]',
    '[class*="Card--"]',
    '[class*="doubleCard"]',
    '[class*="item-card"]',
    '[class*="goods-card"]',
    '[class*="item"]',
    '[class*="Item"]'
  ];

  const handles = await page.$$(selectors.join(','));
  const cards = [];
  const seen = new Set();

  for (const handle of handles.slice(0, 800)) {
    let cardHandle;
    let keepCardHandle = false;
    try {
      cardHandle = await handle.evaluateHandle((el) => {
        const cardSelector = [
          '[data-nid]',
          '[data-itemid]',
          '[data-item-id]',
          '[class*="Card--"]',
          '[class*="doubleCard"]',
          '[class*="item-card"]',
          '[class*="goods-card"]',
          '[class*="item"]',
          '[class*="Item"]'
        ].join(',');
        return el.closest(cardSelector) || el;
      });

      const card = cardHandle.asElement();
      if (!card) continue;

      const meta = await card.evaluate((el) => {
        const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
        const anchor = el.matches?.('a[href*="item.taobao.com/item.htm"], a[href*="detail.tmall.com/item.htm"]')
          ? el
          : el.querySelector('a[href*="item.taobao.com/item.htm"], a[href*="detail.tmall.com/item.htm"]');
        const href = anchor?.href || anchor?.getAttribute('href') || '';
        const itemId = el.getAttribute('data-nid')
          || el.getAttribute('data-itemid')
          || el.getAttribute('data-item-id')
          || href.match(/[?&]id=(\d+)/i)?.[1]
          || '';
        const hasPrice = /[\u00a5\uffe5]\s*\d|\b\d+(?:[.,]\d{1,2})\b/.test(text);
        const hasImage = Boolean(el.querySelector('img'));
        const key = itemId || href || text.slice(0, 120);
        return {
          key,
          ok: Boolean((itemId || href) && hasPrice && hasImage)
        };
      });

      if (!meta.ok || seen.has(meta.key)) continue;
      seen.add(meta.key);
      keepCardHandle = true;
      cards.push(card);
    } catch {
      // Ignore detached or inaccessible nodes.
    } finally {
      if (cardHandle && !keepCardHandle) await cardHandle.dispose().catch(() => {});
    }
  }

  return cards;
}

async function extractFromCard(card) {
  return card.evaluate((el) => {
    const textOf = (selector) => {
      const node = el.querySelector(selector);
      return (node?.innerText || node?.textContent || '').replace(/\s+/g, ' ').trim();
    };

    const attrOf = (selector, attr) => {
      const node = el.querySelector(selector);
      return node?.getAttribute(attr) || '';
    };

    const normalizeUrl = (value) => {
      if (!value) return '';
      if (value.startsWith('//')) return `https:${value}`;
      return value;
    };

    const firstUsefulImage = (image) => {
      if (!image) return '';
      const candidates = [
        image.getAttribute('data-src'),
        image.getAttribute('data-lazy-src'),
        image.getAttribute('data-ks-lazyload'),
        image.getAttribute('src'),
        image.currentSrc,
        image.src
      ].filter(Boolean);
      return candidates.find((value) => !/blank\.gif|data:image|placeholder/i.test(value))
        || candidates[0]
        || '';
    };

    const cleanPriceText = (value) => {
      const text = String(value || '')
        .replace(/\s+/g, ' ')
        .replace(/[\u00a5\uffe5]\s+/g, '\uffe5')
        .trim();
      const match = text.match(/[\u00a5\uffe5]\s*\d+(?:\s*[.,]\s*\d+)?/)
        || text.match(/\b\d+(?:\s*[.,]\s*\d{1,2})?\b/);
      return match ? match[0].replace(/\s*([.,])\s*/g, '$1') : '';
    };

    const cleanDescText = (value) => String(value || '')
      .replace(/[\u00a5\uffe5]\s*\d+(?:\s*[.,]\s*\d+)?/g, ' ')
      .replace(/[\u00a5\uffe5]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();

    const lines = Array.from(new Set((el.innerText || el.textContent || '')
      .split(/\n+/)
      .map((line) => line.replace(/\s+/g, ' ').trim())
      .filter(Boolean)));
    const fullText = lines.join(' ');

    const anchor = el.matches?.('a[href*="item.taobao.com/item.htm"], a[href*="detail.tmall.com/item.htm"]')
      ? el
      : el.querySelector([
        'a[href*="item.taobao.com/item.htm"]',
        'a[href*="detail.tmall.com/item.htm"]',
        'a[href*="//item.taobao.com/item.htm"]',
        'a[href*="//detail.tmall.com/item.htm"]'
      ].join(','));
    const image = el.querySelector('img');
    const href = normalizeUrl(anchor?.href || anchor?.getAttribute('href') || '');
    const itemId = el.getAttribute('data-nid')
      || el.getAttribute('data-itemid')
      || el.getAttribute('data-item-id')
      || href.match(/[?&]id=(\d+)/i)?.[1]
      || '';

    const priceText = textOf('[class*="price"]')
      || textOf('[class*="Price"]')
      || textOf('[class*="PRICE"]')
      || textOf('[class*="money"]')
      || textOf('[class*="Money"]');

    const priceFromText = (() => {
      const compact = fullText
        .replace(/\s+/g, ' ')
        .replace(/[\u00a5\uffe5]\s+/g, '\u00a5');
      const match = compact.match(/[\u00a5\uffe5]\s*\d+(?:[.,]\d+)?/)
        || compact.match(/\b\d+(?:[.,]\d{1,2})\b/);
      return match ? match[0] : '';
    })();

    const priceRaw = cleanPriceText(priceText) || cleanPriceText(priceFromText);

    const title = textOf('[class*="title"]')
      || textOf('[class*="Title"]')
      || textOf('[class*="name"]')
      || textOf('[class*="Name"]')
      || attrOf('a[title]', 'title')
      || anchor?.getAttribute('title')
      || image?.getAttribute('alt')
      || lines.find((line) => {
        if (line === priceRaw) return false;
        if (/^[\u00a5\uffe5]?\s*\d+(?:[.,]\d+)?$/.test(line)) return false;
        if (/^(广告|找相似|进店|付款|人付款|包邮|天猫|淘宝)$/.test(line)) return false;
        return line.length >= 4;
      })
      || '';

    const seller = textOf('[class*="shop"]')
      || textOf('[class*="Shop"]')
      || textOf('[class*="seller"]')
      || textOf('[class*="Seller"]')
      || textOf('[class*="nick"]')
      || textOf('[class*="Nick"]')
      || '';

    const location = textOf('[class*="location"]')
      || textOf('[class*="Location"]')
      || textOf('[class*="procity"]')
      || textOf('[class*="area"]')
      || textOf('[class*="Area"]')
      || lines.find((line) => /^[\u4e00-\u9fa5]{2,8}(?:\s+[\u4e00-\u9fa5]{2,8})?$/.test(line) && !line.includes('店'))
      || '';

    const desc = cleanDescText(textOf('[class*="promo"]')
      || textOf('[class*="Promo"]')
      || textOf('[class*="subTitle"]')
      || textOf('[class*="subtitle"]')
      || lines
        .filter((line) => {
          if (line === title || line === priceRaw || line === seller || line === location) return false;
          if (title && line.includes(title)) return false;
          if (priceRaw && line.includes(priceRaw)) return false;
          if (seller && line.includes(seller)) return false;
          if (location && line.includes(location)) return false;
          return true;
        })
        .slice(0, 4)
        .join(' '));

    return {
      title,
      price_raw: priceRaw,
      desc,
      seller,
      location,
      url: href || (itemId ? `https://item.taobao.com/item.htm?id=${itemId}` : ''),
      image_url: normalizeUrl(firstUsefulImage(image))
    };
  });
}

function normalize(rawItem, context) {
  return normalizeItem({ ...rawItem, site }, { ...context, site });
}

module.exports = { site, stayVisibleAfterRecovery, search, match, findCards, extractFromCard, normalize };
