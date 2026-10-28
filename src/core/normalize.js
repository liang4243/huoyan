const { normalizeUrl, parsePrice, repairMojibake } = require('./utils');

function cleanText(value) {
  return repairMojibake(value).replace(/\s+/g, ' ').trim();
}

function normalizeItem(rawItem, context) {
  const site = rawItem.site || context.site;
  const keyword = context.keyword || '';
  const pageUrl = context.pageUrl || '';

  const title = cleanText(rawItem.title);
  const priceRaw = cleanText(rawItem.price_raw || rawItem.priceRaw);
  const price = rawItem.price == null ? parsePrice(priceRaw) : parsePrice(rawItem.price);
  const url = normalizeUrl(rawItem.url, pageUrl);

  if (!title || !priceRaw || price == null || !url) return null;

  return {
    id: '',
    site,
    keyword,
    title,
    price_raw: priceRaw,
    price,
    desc: cleanText(rawItem.desc),
    seller: cleanText(rawItem.seller),
    location: cleanText(rawItem.location),
    url,
    image_url: normalizeUrl(rawItem.image_url || rawItem.imageUrl, pageUrl),
    image_local_path: null,
    extract_time: context.extractTime,
    risk_flags: [],
    positive_flags: [],
    rule_label: 'yellow',
    rule_score: 60,
    rule_reason: '',
    scoring_method: 'local_keyword_rules_v1',
    needs_ai_review: true,
    ai_label: null,
    ai_score: null,
    ai_reason: '',
    ai_questions: [],
    initial_label: 'yellow',
    score: 60,
    note: ''
  };
}

function assignIds(items, site, dateText) {
  return items.map((item, index) => ({
    ...item,
    id: `${site}_${dateText}_${String(index + 1).padStart(4, '0')}`
  }));
}

module.exports = {
  assignIds,
  normalizeItem
};
