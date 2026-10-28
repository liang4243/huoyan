function productIdentity(value) {
  const text = String(value || '').trim();
  let url;
  try { url = new URL(/^\d+$/.test(text) ? `https://item.taobao.com/item.htm?id=${text}` : text); }
  catch { throw new Error('Expected a product ID or supported product URL.'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.port) {
    throw new Error('Invalid product URL.');
  }
  const host = url.hostname;
  let site, id, canonical;
  if (['item.taobao.com', 'detail.tmall.com', 'detail.tmall.hk'].includes(host) && url.pathname === '/item.htm') {
    site = 'taobao'; id = url.searchParams.get('id'); canonical = `https://${host}/item.htm?id=${id}`;
  } else if (host === 'item.jd.com' && /^\/\d+\.html$/.test(url.pathname)) {
    site = 'jd'; id = url.pathname.match(/\d+/)[0]; canonical = `https://${host}/${id}.html`;
  } else if (host === 'www.goofish.com' && url.pathname === '/item') {
    site = 'goofish'; id = url.searchParams.get('id'); canonical = `https://${host}/item?id=${id}`;
  } else if (host === 'detail.1688.com' && /^\/offer\/\d+\.html$/.test(url.pathname)) {
    site = '1688'; id = url.pathname.match(/\d+/)[0]; canonical = `https://${host}/offer/${id}.html`;
  } else if (host === 'mobile.yangkeduo.com' && url.pathname === '/goods.html') {
    site = 'pinduoduo'; id = url.searchParams.get('goods_id'); canonical = `https://${host}/goods.html?goods_id=${id}`;
  }
  if (!site || !/^\d+$/.test(id || '')) throw new Error('Unsupported product URL or missing numeric product ID.');
  return { key: `${site}:${id}`, site, productId: id, url: canonical };
}

module.exports = { productIdentity };
