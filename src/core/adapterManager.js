const goofish = require('../adapters/goofish');
const jd = require('../adapters/jd');
const taobao = require('../adapters/taobao');
const site1688 = require('../adapters/1688');
const smzdm = require('../adapters/smzdm');
const pinduoduo = require('../adapters/pinduoduo');

const adapters = [goofish, jd, taobao, site1688, smzdm, pinduoduo];

function listAdapters() {
  return adapters;
}

function getAdapter(site) {
  return adapters.find((adapter) => adapter.site === site);
}

function matchAdapter(url, preferredSite = 'auto') {
  if (preferredSite && preferredSite !== 'auto') {
    const adapter = getAdapter(preferredSite);
    return adapter && adapter.match(url) ? adapter : null;
  }
  return adapters.find((adapter) => adapter.match(url)) || null;
}

async function selectPageForSite(pages, preferredSite = 'auto') {
  const candidates = [];
  for (const page of pages) {
    const url = page.url();
    if (!url || url === 'about:blank') continue;
    const adapter = matchAdapter(url, preferredSite);
    if (adapter) candidates.push({ page, adapter, url });
  }

  if (candidates.length > 0) return candidates[candidates.length - 1];
  return null;
}

module.exports = {
  getAdapter,
  listAdapters,
  matchAdapter,
  selectPageForSite
};
