const { normalizeItem } = require('../core/normalize');

const site = 'smzdm';

function match(url) {
  return /(^|\.)smzdm\.com/i.test(url);
}

async function findCards() {
  // TODO: Add SMZDM DOM selectors in a later adapter pass.
  return [];
}

async function extractFromCard() {
  return {};
}

function normalize(rawItem, context) {
  return normalizeItem({ ...rawItem, site }, { ...context, site });
}

module.exports = { site, match, findCards, extractFromCard, normalize };
