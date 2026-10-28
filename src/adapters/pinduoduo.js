const { normalizeItem } = require('../core/normalize');

const site = 'pinduoduo';

// Pinduoduo has no desktop search; the mobile web app on mobile.yangkeduo.com
// requires a phone-sized viewport and mobile UA to render the item list.
// Keep the Chrome version in sync with the local Chrome.
const browser = {
  userAgent: 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Mobile Safari/537.36',
  viewport: { width: 414, height: 896 },
  isMobile: true,
  hasTouch: true
};

const search = {
  buildUrl(keyword) {
    return `https://mobile.yangkeduo.com/search_result.html?search_key=${encodeURIComponent(keyword || '')}`;
  },
  // Search is URL-driven; results load progressively while scrolling.
  searchButtonSelectors: [],
  nextButtonSelectors: []
};

function match(url) {
  return /(^|\.)yangkeduo\.com/i.test(url) || /(^|\.)pinduoduo\.com/i.test(url);
}

// The list renders items as divs (no anchors, no hrefs). The authoritative
// data (goodsID, goodsName, price in cents, salesTip) lives in the card's
// React props, so both card discovery and extraction read that object.
async function findCards(page) {
  const handles = await page.$$('[class] > [data-uniqid], ._3glhOBhU');
  const cards = [];
  const seen = new Set();

  for (const handle of handles.slice(0, 400)) {
    try {
      const meta = await handle.evaluate((el) => {
        const findGoods = () => {
          for (const key of Object.keys(el)) {
            if (!key.startsWith('__reactFiber$') && !key.startsWith('__reactProps$')) continue;
            const fiber = el[key];
            const props = fiber && fiber.memoizedProps ? fiber.memoizedProps : fiber;
            const kids = props && props.children;
            const candidates = Array.isArray(kids) ? kids : kids && kids.props ? [kids.props] : [];
            for (const candidate of candidates) {
              const goods = candidate && candidate.goods;
              if (goods && (goods.goodsID || goods.goods_id)) return goods;
            }
            if (props && props.goods && (props.goods.goodsID || props.goods.goods_id)) return props.goods;
          }
          return null;
        };
        const goods = findGoods();
        if (!goods) return null;
        const id = String(goods.goodsID || goods.goods_id);
        const name = String(goods.goodsName || goods.goods_name || '');
        const price = Number(goods.price);
        return { id, ok: Boolean(id && (name.length >= 4 || price > 0)) };
      });
      if (!meta || !meta.ok || seen.has(meta.id)) continue;
      seen.add(meta.id);
      cards.push(handle);
    } catch {
      // Ignore detached nodes during lazy-load churn.
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

    const lines = Array.from(new Set((el.innerText || el.textContent || '')
      .split(/\n+/)
      .map((line) => line.replace(/\s+/g, ' ').trim())
      .filter(Boolean)));

    let goods = null;
    for (const key of Object.keys(el)) {
      if (!key.startsWith('__reactFiber$') && !key.startsWith('__reactProps$')) continue;
      const fiber = el[key];
      const props = fiber && fiber.memoizedProps ? fiber.memoizedProps : fiber;
      const kids = props && props.children;
      const candidates = Array.isArray(kids) ? kids : kids && kids.props ? [kids.props] : [];
      for (const candidate of candidates) {
        if (candidate && candidate.goods && (candidate.goods.goodsID || candidate.goods.goods_id)) {
          goods = candidate.goods;
          break;
        }
      }
      if (goods) break;
      if (props && props.goods && (props.goods.goodsID || props.goods.goods_id)) goods = props.goods;
      if (goods) break;
    }

    const goodsId = goods ? String(goods.goodsID || goods.goods_id || '') : '';
    const title = (goods && (goods.goodsName || goods.goods_name)) || '';
    const salesTip = (goods && (goods.salesTip || goods.sales_tip)) || '';

    const image = el.querySelector('img');
    const imageCandidates = image ? [
      image.getAttribute('data-src'),
      image.getAttribute('src'),
      image.currentSrc,
      image.src
    ].filter(Boolean) : [];
    const rawImage = imageCandidates.find((value) => !/blank|data:image/i.test(value)) || imageCandidates[0] || '';

    // DOM price text is the user-visible one ("券后¥60.13"); the React price
    // is integer cents.
    const fullText = lines.join(' ');
    const domPrice = fullText.match(/[\uffe5\u00a5]\s*\d+(?:\.\d{1,2})?/);
    const reactPrice = goods && Number(goods.price) > 0
      ? `\u00a5${(Number(goods.price) / 100).toFixed(2)}`
      : '';
    const priceRaw = domPrice ? domPrice[0].replace(/\s+/g, '') : reactPrice;

    return {
      title,
      price_raw: priceRaw,
      desc: [salesTip].filter(Boolean).join(' '),
      seller: '',
      location: '',
      url: goodsId ? `https://mobile.yangkeduo.com/goods.html?goods_id=${goodsId}` : '',
      image_url: rawImage.startsWith('//') ? `https:${rawImage}` : rawImage,
      extra: salesTip ? { sold: salesTip } : undefined
    };
  });
}

function normalize(rawItem, context) {
  return normalizeItem({ ...rawItem, site }, { ...context, site });
}

module.exports = {
  site,
  browser,
  search,
  match,
  findCards,
  extractFromCard,
  normalize
};
