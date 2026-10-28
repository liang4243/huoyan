function buildSearchUrl(adapter, keyword) {
  if (!adapter || typeof adapter.search?.buildUrl !== 'function') return '';
  return adapter.search.buildUrl(keyword || '');
}

module.exports = {
  buildSearchUrl
};
