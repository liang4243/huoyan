const dayjs = require('dayjs');
const iconv = require('iconv-lite');

function parsePrice(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (!value) return null;

  const text = String(value)
    .replace(/,/g, '')
    .replace(/\s+/g, '');

  const match = text.match(/(?:\u00a5|\uffe5|RMB|CNY)?(\d+(?:\.\d+)?)(?:\u5143)?/i);
  if (!match) return null;

  const price = Number.parseFloat(match[1]);
  return Number.isFinite(price) ? price : null;
}

function normalizeUrl(url, baseUrl) {
  if (!url) return '';
  try {
    return new URL(url, baseUrl).toString();
  } catch {
    return String(url);
  }
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function safeFilePart(value) {
  const text = String(value || 'unknown')
    .trim()
    .replace(/[\\/:*?"<>|#%&{}$!'@+`=]/g, '_')
    .replace(/\s+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '');
  return text || 'unknown';
}

function timestampForFile(date = new Date()) {
  return dayjs(date).format('YYYYMMDD_HHmmss');
}

function isoNow() {
  return dayjs().format();
}

function truncate(text, length) {
  const value = String(text || '').replace(/\s+/g, ' ').trim();
  if (value.length <= length) return value;
  return `${value.slice(0, Math.max(0, length - 3))}...`;
}

function scoreReadableChinese(text) {
  const value = String(text || '');
  const badChars = (value.match(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffd]/g) || []).length;
  const commonHints = [
    '\u7684', '\u4e00', '\u662f', '\u5728', '\u6709', '\u548c',
    '\u5546', '\u54c1', '\u4ef7', '\u683c', '\u5356', '\u5bb6',
    '\u5730', '\u533a', '\u652f', '\u6301', '\u6b63', '\u5e38',
    '\u4f7f', '\u7528', '\u529f', '\u80fd', '\u6d4b', '\u8bd5',
    '\u539f', '\u88c5', '\u914d', '\u4ef6', '\u4eac', '\u4e1c',
    '\u95f2', '\u9c7c', '\u81ea', '\u63d0'
  ];
  const hits = commonHints.reduce((count, hint) => count + (value.includes(hint) ? 1 : 0), 0);
  return hits - badChars * 5;
}

function repairMojibake(value) {
  const text = String(value || '');
  if (!text) return '';

  try {
    const repaired = iconv.decode(iconv.encode(text, 'gb18030'), 'utf8');
    return scoreReadableChinese(repaired) > scoreReadableChinese(text) + 2 ? repaired : text;
  } catch {
    return text;
  }
}

function dedupeItems(items) {
  const seen = new Set();
  const output = [];

  for (const item of items) {
    const key = item.url
      ? `url:${item.url}`
      : `fallback:${item.title}|${item.price}|${item.seller}`;
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(item);
  }

  return output;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomInt(min, max) {
  const low = Math.ceil(Math.min(min, max));
  const high = Math.floor(Math.max(min, max));
  return Math.floor(Math.random() * (high - low + 1)) + low;
}

async function sleepRandom(minMs, maxMs) {
  const delay = randomInt(minMs, maxMs);
  await sleep(delay);
  return delay;
}

module.exports = {
  clamp,
  dedupeItems,
  isoNow,
  normalizeUrl,
  parsePrice,
  randomInt,
  repairMojibake,
  safeFilePart,
  sleep,
  sleepRandom,
  timestampForFile,
  truncate
};
