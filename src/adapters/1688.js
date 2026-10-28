const { normalizeItem } = require('../core/normalize');
const iconv = require('iconv-lite');

const site = '1688';

// The legacy offer_search.htm endpoint decodes its keywords parameter as
// GBK; a UTF-8 encodeURIComponent keyword comes back as mojibake and an
// empty result list ("哎呦喂，这里空空如也"). ASCII keywords are unaffected,
// which is why this went unnoticed with latin keywords.
function gbkPercentEncode(text) {
  const bytes = iconv.encode(String(text || ''), 'gbk');
  let out = '';
  for (const byte of bytes) {
    const c = String.fromCharCode(byte);
    out += /[A-Za-z0-9\-_.!~*'()]/.test(c) ? c : `%${byte.toString(16).toUpperCase().padStart(2, '0')}`;
  }
  return out;
}

const search = {
  buildUrl(keyword) {
    return `https://s.1688.com/selloffer/offer_search.htm?keywords=${gbkPercentEncode(keyword)}`;
  },
  searchButtonSelectors: [
    'button[type="submit"]',
    '.search-button',
    '[class*="search"] button',
    '[class*="Search"] button',
    'form button'
  ],
  nextButtonSelectors: [
    'a[rel="next"]',
    '.fui-next',
    '.next',
    '[class*="next"]',
    'button[aria-label*="next" i]',
    'a[aria-label*="next" i]',
    'button[title*="下一页"]',
    'a[title*="下一页"]'
  ]
};

function match(url) {
  return /(^|\.)1688\.com/i.test(url);
}

const DETAIL_ANCHOR_SELECTORS = [
  'a[href*="detail.1688.com/offer"]',
  'a[href*="/offer/"]',
  'a[href*="detail.m.1688.com/page/index.html"][href*="offerId="]'
].join(',');

// The current results page wraps each card in an <a> (class ocms-fusion-*)
// whose child is .search-offer-item, and organic cards hydrate slowly behind
// skeleton placeholders — wait for real rows before scanning.
async function findCards(page) {
  try {
    await page.waitForSelector('.offer-title-row, [data-offer-id], .sm-offer-item', { timeout: 8000 });
  } catch {
    // Fall through and scan whatever rendered.
  }

  const selectors = [
    '[data-offer-id]',
    '[data-offerid]',
    '[offer-id]',
    '.sm-offer-item',
    '.offer-item',
    '.common-offer-card',
    '.search-offer-item',
    '.fy23-search-card',
    '.seb-card',
    '.list-item',
    '[class*="offer"]',
    '[class*="Offer"]',
    '[class*="product"]',
    '[class*="Product"]',
    'a[href*="detail.1688.com/offer"]',
    'a[href*="detail.m.1688.com/page/index.html"][href*="offerId="]'
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
          '[data-offer-id]',
          '[data-offerid]',
          '[offer-id]',
          '.search-offer-wrapper',
          '.sm-offer-item',
          '.offer-item',
          '.common-offer-card',
          '.search-offer-item',
          '.fy23-search-card',
          '.seb-card',
          '.list-item',
          '[class*="offer"]',
          '[class*="Offer"]',
          '[class*="product"]',
          '[class*="Product"]'
        ].join(',');
        return el.closest(cardSelector) || el;
      });

      const card = cardHandle.asElement();
      if (!card) continue;

      const meta = await card.evaluate((el) => {
        const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
        // The card may be wrapped BY an <a> (not contain one), e.g. the
        // ocms-fusion ad/organic offer cards on the current page.
        const anchor = el.matches?.('a[href]')
          ? el
          : el.querySelector('a[href*="detail.1688.com/offer"], a[href*="/offer/"], a[href*="detail.m.1688.com/page/index.html"][href*="offerId="], a[href]')
            || el.closest?.('a[href]')
            || null;
        const offerId = el.getAttribute('data-offer-id')
          || el.getAttribute('data-offerid')
          || el.getAttribute('offer-id')
          || anchor?.href?.match(/offer\/(\d+)\.html/i)?.[1]
          || anchor?.href?.match(/[?&]offerId=(\d+)/i)?.[1]
          || '';
        const hasPrice = /[\u00a5\uffe5]\s*\d|\d+(?:[.,]\d+)?\s*(?:\u5143|\u8d77)/.test(text);
        const hasImage = Boolean(el.querySelector('img'));
        const href = anchor?.href || '';
        const key = offerId || href || text.slice(0, 120);
        return {
          key,
          ok: Boolean((offerId || href) && hasPrice && hasImage)
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

    const normalizeImageUrl = (value) => {
      if (!value) return '';
      if (value.startsWith('//')) return `https:${value}`;
      return value;
    };

    const normalizeProductUrl = (value) => {
      if (!value) return '';
      if (value.startsWith('//')) return `https:${value}`;
      if (value.startsWith('/offer/')) return `https://detail.1688.com${value}`;
      const offerId = String(value).match(/[?&]offerId=(\d+)/i)?.[1];
      if (offerId) return `https://detail.1688.com/offer/${offerId}.html`;
      return value;
    };

    const firstUsefulImage = (image) => {
      if (!image) return '';
      const candidates = [
        image.getAttribute('data-lazy-src'),
        image.getAttribute('data-src'),
        image.getAttribute('data-img'),
        image.getAttribute('src'),
        image.currentSrc,
        image.src
      ].filter(Boolean);
      return candidates.find((value) => !/blank\.gif|data:image|placeholder/i.test(value))
        || candidates[0]
        || '';
    };

    const inferLocationFromSeller = (sellerName) => {
      const sellerText = String(sellerName || '').replace(/\s+/g, '').trim();
      if (!sellerText) return '';

      const cityMatch = sellerText.match(/^([\u4e00-\u9fa5]{2,8}?市)/);
      if (cityMatch) return cityMatch[1].replace(/市$/, '');

      const provinceCityMatch = sellerText.match(/^([\u4e00-\u9fa5]{2,8}?省)([\u4e00-\u9fa5]{2,8}?市)/);
      if (provinceCityMatch) {
        return `${provinceCityMatch[1].replace(/省$/, '')} ${provinceCityMatch[2].replace(/市$/, '')}`;
      }

      const knownCityPrefixes = [
        '深圳', '广州', '东莞', '佛山', '中山', '珠海', '惠州', '汕头',
        '义乌', '杭州', '宁波', '温州', '绍兴', '金华', '台州',
        '上海', '北京', '天津', '重庆', '苏州', '无锡', '南京',
        '厦门', '泉州', '福州', '成都', '武汉', '长沙', '郑州',
        '青岛', '济南', '临沂', '西安'
      ];
      return knownCityPrefixes.find((city) => sellerText.startsWith(city)) || '';
    };

    const lines = Array.from(new Set((el.innerText || el.textContent || '')
      .split(/\n+/)
      .map((line) => line.replace(/\s+/g, ' ').trim())
      .filter(Boolean)));
    const fullText = lines.join(' ');

    const anchor = el.matches?.('a[href*="detail.1688.com/offer"], a[href*="detail.m.1688.com/page/index.html"][href*="offerId="]')
      ? el
      : el.querySelector([
        'a[href*="detail.1688.com/offer"]',
        'a[href*="/offer/"]',
        'a[href*="detail.m.1688.com/page/index.html"][href*="offerId="]'
      ].join(','))
        // Current cards are wrapped by an <a> instead of containing one.
        || el.closest?.('a[href]')
        || null;
    const image = el.querySelector('img');

    const offerId = el.getAttribute('data-offer-id')
      || el.getAttribute('data-offerid')
      || el.getAttribute('offer-id')
      || anchor?.href?.match(/offer\/(\d+)\.html/i)?.[1]
      || anchor?.href?.match(/[?&]offerId=(\d+)/i)?.[1]
      || '';

    const priceText = textOf('.price-item')
      || textOf('.hover-price-item')
      || textOf('[class*="price-item"]')
      || textOf('[class*="PriceItem"]')
      || textOf('[class*="price"]')
      || textOf('[class*="Price"]')
      || textOf('[class*="PRICE"]')
      || textOf('[class*="amount"]')
      || textOf('[class*="Amount"]')
      || textOf('[class*="money"]')
      || textOf('[class*="Money"]');

    const priceFromText = (() => {
      const compact = fullText
        .replace(/\s+/g, ' ')
        .replace(/[\u00a5\uffe5]\s+/g, '\u00a5');
      const match = compact.match(/[\u00a5\uffe5]\s*\d+(?:[.,]\d+)?/)
        || compact.match(/\b\d+(?:[.,]\d{1,2})\s*(?:\u5143|\u8d77)/)
        || compact.match(/\b\d+(?:[.,]\d{1,2})\b/);
      return match ? match[0] : '';
    })();

    const priceRaw = (priceText || priceFromText).replace(/\s+/g, '');

    const title = textOf('[class*="title"]')
      || textOf('[class*="Title"]')
      || textOf('[class*="name"]')
      || textOf('[class*="Name"]')
      || attrOf('a[title]', 'title')
      || anchor?.getAttribute('title')
      || image?.getAttribute('alt')
      || lines.find((line) => {
        if (line === priceRaw) return false;
        if (/^[\u00a5\uffe5]?\s*\d+(?:[.,]\d+)?(?:\s*(?:\u5143|\u8d77))?$/.test(line)) return false;
        if (/^(\u5e7f\u544a|\u627e\u76f8\u4f3c|\u8fdb\u5e97|\u6210\u4ea4|\u8d77\u6279|\u8d27\u6e90)$/.test(line)) return false;
        return line.length >= 4;
      })
      || '';

    const seller = textOf('[class*="company"]')
      || textOf('[class*="Company"]')
      || textOf('[class*="shop"]')
      || textOf('[class*="Shop"]')
      || textOf('[class*="seller"]')
      || textOf('[class*="Seller"]')
      || '';

    const location = textOf('[class*="location"]')
      || textOf('[class*="Location"]')
      || textOf('[class*="area"]')
      || textOf('[class*="Area"]')
      || textOf('[class*="province"]')
      || textOf('[class*="Province"]')
      || inferLocationFromSeller(seller);

    const desc = textOf('[class*="desc"]')
      || textOf('[class*="Desc"]')
      || lines
        .filter((line) => line !== title && line !== priceRaw && line !== seller && line !== location)
        .slice(0, 4)
        .join(' ');

    return {
      title,
      price_raw: priceRaw,
      desc,
      seller,
      location,
      url: normalizeProductUrl(anchor?.href || anchor?.getAttribute('href') || (offerId ? `https://detail.1688.com/offer/${offerId}.html` : '')),
      image_url: normalizeImageUrl(firstUsefulImage(image))
    };
  });
}

function normalize(rawItem, context) {
  return normalizeItem({ ...rawItem, site }, { ...context, site });
}

module.exports = { site, search, match, findCards, extractFromCard, normalize };
