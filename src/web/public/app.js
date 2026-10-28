const state = {
  batches: [],
  activeBatch: null,
  items: []
};

const elements = {
  refreshButton: document.querySelector('#refreshButton'),
  batchList: document.querySelector('#batchList'),
  batchTitle: document.querySelector('#batchTitle'),
  batchMeta: document.querySelector('#batchMeta'),
  stats: document.querySelector('#stats'),
  textFilter: document.querySelector('#textFilter'),
  labelFilter: document.querySelector('#labelFilter'),
  minScoreFilter: document.querySelector('#minScoreFilter'),
  sortSelect: document.querySelector('#sortSelect'),
  itemsBody: document.querySelector('#itemsBody'),
  emptyState: document.querySelector('#emptyState')
};

function escapeHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatTime(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
}

function getLabel(item) {
  return item.ai_label || item.rule_label || item.initial_label || 'yellow';
}

function getScore(item) {
  const value = item.ai_score ?? item.rule_score ?? item.score ?? 0;
  return Number.isFinite(Number(value)) ? Number(value) : 0;
}

function labelClass(label) {
  return `label-${['green', 'yellow', 'red', 'gray', 'purple'].includes(label) ? label : 'gray'}`;
}

function truncate(value, length) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (text.length <= length) return text;
  return `${text.slice(0, length - 3)}...`;
}

async function fetchJson(url) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `请求失败：${response.status}`);
  }
  return payload;
}

function renderBatches() {
  if (state.batches.length === 0) {
    elements.batchList.innerHTML = '<div class="empty-state show">还没有 JSONL 采集结果</div>';
    return;
  }

  elements.batchList.innerHTML = state.batches.map((batch) => {
    const active = state.activeBatch?.file === batch.file ? ' active' : '';
    return `
      <button class="batch-item${active}" type="button" data-file="${escapeHtml(batch.file)}">
        <strong>${escapeHtml(batch.keyword)} · ${escapeHtml(batch.site)}</strong>
        <span>${escapeHtml(batch.itemCount)} 条 · ${escapeHtml(formatTime(batch.modifiedTime))}</span>
      </button>
    `;
  }).join('');
}

function renderHeader() {
  const batch = state.activeBatch;
  if (!batch) {
    elements.batchTitle.textContent = '选择一个采集批次';
    elements.batchMeta.textContent = '读取 data/raw 下的 JSONL 文件';
    elements.stats.innerHTML = '';
    return;
  }

  elements.batchTitle.textContent = `${batch.keyword} · ${batch.site}`;
  elements.batchMeta.textContent = `${batch.file} · ${formatTime(batch.modifiedTime)}`;
  const labels = batch.labels || {};
  elements.stats.innerHTML = ['green', 'yellow', 'purple', 'red', 'gray'].map((label) => (
    `<span class="badge ${labelClass(label)}">${label} ${labels[label] || 0}</span>`
  )).join('');
}

function getFilteredItems() {
  const text = elements.textFilter.value.trim().toLowerCase();
  const label = elements.labelFilter.value;
  const minScoreText = elements.minScoreFilter.value;
  const minScore = minScoreText === '' ? null : Number(minScoreText);

  const filtered = state.items.filter((item) => {
    const itemLabel = getLabel(item);
    if (label && itemLabel !== label) return false;
    if (minScore != null && getScore(item) < minScore) return false;
    if (!text) return true;

    const haystack = [
      item.title,
      item.desc,
      item.seller,
      item.location,
      item.price_raw,
      ...(item.risk_flags || []),
      ...(item.positive_flags || [])
    ].join(' ').toLowerCase();
    return haystack.includes(text);
  });

  const sortBy = elements.sortSelect.value;
  filtered.sort((a, b) => {
    if (sortBy === 'score-asc') return getScore(a) - getScore(b);
    if (sortBy === 'price-asc') return (a.price ?? Number.MAX_SAFE_INTEGER) - (b.price ?? Number.MAX_SAFE_INTEGER);
    if (sortBy === 'price-desc') return (b.price ?? -1) - (a.price ?? -1);
    if (sortBy === 'id-asc') return String(a.id || '').localeCompare(String(b.id || ''), 'zh-CN');
    return getScore(b) - getScore(a);
  });

  return filtered;
}

function renderItems() {
  const items = getFilteredItems();
  elements.emptyState.classList.toggle('show', items.length === 0);
  elements.itemsBody.innerHTML = items.map((item) => {
    const label = getLabel(item);
    const risk = (item.risk_flags || []).join('，');
    const positive = (item.positive_flags || []).join('，');
    const image = item.image_url
      ? `<img class="thumb" src="${escapeHtml(item.image_url)}" alt="">`
      : '<div class="thumb"></div>';
    return `
      <tr>
        <td>${image}</td>
        <td>
          <div class="title">${escapeHtml(item.title || '(无标题)')}</div>
          <div class="desc">${escapeHtml(truncate(item.desc || item.rule_reason || '', 120))}</div>
        </td>
        <td class="price">${escapeHtml(item.price_raw || item.price || '')}</td>
        <td><span class="label-pill ${labelClass(label)}">${escapeHtml(label)}</span></td>
        <td>${escapeHtml(getScore(item))}</td>
        <td>${escapeHtml(item.location || '')}</td>
        <td>${escapeHtml(item.seller || '')}</td>
        <td class="flags">
          <div class="risk">${escapeHtml(risk)}</div>
          <div class="positive">${escapeHtml(positive)}</div>
        </td>
        <td>
          <div class="actions">
            ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">打开商品</a>` : ''}
            ${item.image_url ? `<a href="${escapeHtml(item.image_url)}" target="_blank" rel="noreferrer">查看图片</a>` : ''}
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

async function loadBatch(file) {
  const payload = await fetchJson(`/api/items?file=${encodeURIComponent(file)}`);
  state.items = payload.items || [];
  state.activeBatch = state.batches.find((batch) => batch.file === file) || state.activeBatch;
  renderBatches();
  renderHeader();
  renderItems();
}

async function loadBatches() {
  const payload = await fetchJson('/api/batches');
  state.batches = payload.batches || [];
  if (!state.activeBatch && state.batches[0]) {
    state.activeBatch = state.batches[0];
  } else if (state.activeBatch) {
    state.activeBatch = state.batches.find((batch) => batch.file === state.activeBatch.file) || state.batches[0] || null;
  }
  renderBatches();
  renderHeader();
  if (state.activeBatch) {
    await loadBatch(state.activeBatch.file);
  } else {
    state.items = [];
    renderItems();
  }
}

elements.refreshButton.addEventListener('click', () => {
  loadBatches().catch((error) => {
    elements.emptyState.textContent = error.message;
    elements.emptyState.classList.add('show');
  });
});

elements.batchList.addEventListener('click', (event) => {
  const button = event.target.closest('[data-file]');
  if (!button) return;
  loadBatch(button.dataset.file).catch((error) => {
    elements.emptyState.textContent = error.message;
    elements.emptyState.classList.add('show');
  });
});

for (const input of [elements.textFilter, elements.labelFilter, elements.minScoreFilter, elements.sortSelect]) {
  input.addEventListener('input', renderItems);
}

loadBatches().catch((error) => {
  elements.emptyState.textContent = error.message;
  elements.emptyState.classList.add('show');
});
