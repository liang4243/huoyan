const { normalizeItem } = require('../core/normalize');

const site = 'jd';

const search = {
  buildUrl(keyword) {
    return `https://search.jd.com/Search?keyword=${encodeURIComponent(keyword || '')}&enc=utf-8`;
  },
  searchButtonSelectors: [
    '#J_search button',
    '.search-m button',
    'form button[type="submit"]',
    'button[type="submit"]'
  ],
  nextButtonSelectors: [
    'a.pn-next',
    '.pn-next',
    'a.fp-next',
    '.fp-next',
    '.page .next',
    'a[aria-label*="next" i]',
    'a[title*="next" i]'
  ]
};

function match(url) {
  return /(^|\.)jd\.com/i.test(url);
}

async function findCards(page) {
  const selectors = [
    '[class*="goodsCardWrapper"]',
    'li.gl-item',
    '.gl-item[data-sku]',
    '#J_goodsList li',
    '.goods-list-v2 li',
    '[class*="goods-item"]',
    '[class*="product-item"]'
  ];

  const handles = await page.$$(selectors.join(','));
  const cards = [];
  const seen = new Set();

  for (const handle of handles.slice(0, 500)) {
    try {
      const meta = await handle.evaluate((el) => {
        const text = (el.innerText || el.textContent || '').trim();
        const sku = el.getAttribute('data-sku')
          || el.querySelector('[data-sku]')?.getAttribute('data-sku')
          || '';
        const href = el.querySelector('a[href*="item.jd.com"], a[href*="//item.jd.com"], a[href*="/item"]')?.href || '';
        const chatHref = el.querySelector('a[href*="chat.jd.com"][href*="pid="]')?.href || '';
        const title = el.querySelector('.p-name, [class*="p-name"], [class*="goods_title"], [class*="name"], a[title], img[alt]');
        const image = el.querySelector('.p-img img, [class*="p-img"] img, img');
        const hasPrice = /[\u00a5\uffe5]\s*\d|\d+\s*\.\s*\d{1,2}/.test(text);
        return {
          key: sku || href || chatHref || text.slice(0, 80),
          ok: Boolean((sku || href || chatHref) && (title || chatHref) && (hasPrice || image || chatHref))
        };
      });

      if (!meta.ok || seen.has(meta.key)) continue;
      seen.add(meta.key);
      cards.push(handle);
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
      return (node?.innerText || node?.textContent || '').replace(/\s+/g, ' ').trim();
    };

    const attrOf = (selector, attr) => {
      const node = el.querySelector(selector);
      return node?.getAttribute(attr) || '';
    };

    const normalizeImageUrl = (value) => {
      if (!value) return '';
      if (value.startsWith('//')) return `https:${value}`;
      return value;
    };

    const decodeMaybe = (value) => {
      let text = String(value || '');
      for (let index = 0; index < 3; index += 1) {
        try {
          const decoded = decodeURIComponent(text);
          if (decoded === text) break;
          text = decoded;
        } catch {
          break;
        }
      }
      return text;
    };

    const parseChatMeta = (href) => {
      if (!href) return {};
      const text = String(href).replace(/&amp;/g, '&');
      const readParam = (name) => {
        const match = text.match(new RegExp(`[?&]${name}=([^&]*)`));
        return match ? match[1] : '';
      };
      return {
        pid: readParam('pid'),
        title: decodeMaybe(readParam('wname')),
        seller: decodeMaybe(readParam('seller')),
        stock: decodeMaybe(readParam('stock')),
        imagePath: decodeMaybe(readParam('imgUrl'))
      };
    };

    const lines = Array.from(new Set((el.innerText || el.textContent || '')
      .split(/\n+/)
      .map((line) => line.replace(/\s+/g, ' ').trim())
      .filter(Boolean)));
    const fullText = lines.join(' ');

    const sku = el.getAttribute('data-sku')
      || el.querySelector('[data-sku]')?.getAttribute('data-sku')
      || '';

    const anchor = el.querySelector(
      '.p-name a[href], [class*="p-name"] a[href], a[href*="item.jd.com"], a[href*="//item.jd.com"], a[href*="/item"]'
    );
    const chatAnchor = el.querySelector('a[href*="chat.jd.com"][href*="pid="]');
    const chatMeta = parseChatMeta(chatAnchor?.getAttribute('href') || chatAnchor?.href || '');
    const productId = sku || chatMeta.pid || '';

    const image = el.querySelector('.p-img img, [class*="p-img"] img, img');
    const imageCandidates = image ? [
      image.getAttribute('data-lazy-img'),
      image.getAttribute('data-img'),
      image.getAttribute('data-src'),
      image.getAttribute('src'),
      image.currentSrc,
      image.src
    ].filter(Boolean) : [];
    const rawImage = imageCandidates.find((value) => !/blank\.gif|data:image/i.test(value))
      || imageCandidates[0]
      || (chatMeta.imagePath ? `https://img10.360buyimg.com/n7/${chatMeta.imagePath}` : '')
      || '';

    const priceText = textOf('.p-price')
      || textOf('[class*="p-price"]')
      || textOf('[class*="price"]')
      || textOf('.p-price i')
      || textOf('[class*="p-price"] i')
      || textOf('[class*="price"] i');

    const priceFromText = (() => {
      const compact = fullText
        .replace(/\s+/g, ' ')
        .replace(/[\u00a5\uffe5]\s+/g, '\u00a5');
      const match = compact.match(/[\u00a5\uffe5]\s*\d+(?:[.,]\d+)?/)
        || compact.match(/\b\d+(?:[.,]\d{1,2})\b/);
      return match ? match[0] : '';
    })();

    const priceRaw = (priceText || priceFromText).replace(/\s+/g, '');

    const title = textOf('.p-name em')
      || textOf('.p-name a')
      || textOf('[class*="p-name"] em')
      || textOf('[class*="p-name"] a')
      // New React search page: the full title sits in a title attribute of
      // the goods title span, with keyword highlights inside as <font> nodes.
      || textOf('[class*="goods_title"] span[title]')
      || textOf('[class*="goods_title"]')
      || attrOf('a[title]', 'title')
      || anchor?.getAttribute('title')
      || image?.getAttribute('alt')
      || chatMeta.title
      || lines.find((line) => {
        if (line === priceRaw) return false;
        if (/^[\u00a5\uffe5]?\s*\d+(?:[.,]\d+)?$/.test(line)) return false;
        if (/^(广告|自营|京东物流|放心购)$/.test(line)) return false;
        return line.length >= 4;
      })
      || '';

    const desc = textOf('.p-name')
      || textOf('[class*="promo"]')
      || lines.filter((line) => line !== title && line !== priceRaw).slice(0, 4).join(' ');

    const seller = textOf('.p-shop a')
      || textOf('.p-shop')
      || textOf('[class*="p-shop"] a')
      || textOf('[class*="shop"] a')
      || textOf('[class*="shop"]')
      // New React search page renders the seller as a span with a hashed
      // `_limit_` class at the bottom of the card.
      || textOf('span[class*="_limit_"]')
      || chatMeta.seller
      || '';

    const location = textOf('[class*="stock"]')
      || textOf('[class*="area"]')
      || textOf('[class*="location"]')
      || chatMeta.stock
      || '';

    return {
      title,
      price_raw: priceRaw,
      desc,
      seller,
      location,
      url: anchor?.href || (productId ? `https://item.jd.com/${productId}.html` : ''),
      image_url: normalizeImageUrl(rawImage)
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
