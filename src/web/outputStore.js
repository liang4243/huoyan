const path = require('path');
const fs = require('fs-extra');

function parseOutputName(fileName) {
  const stem = fileName.replace(/\.jsonl$/i, '');
  const match = stem.match(/^([^_]+)_(.+)_(\d{8}_\d{6})$/);
  if (!match) {
    return {
      site: 'unknown',
      keyword: stem,
      timestamp: ''
    };
  }

  return {
    site: match[1],
    keyword: match[2],
    timestamp: match[3]
  };
}

function getLabel(item) {
  return item.ai_label || item.rule_label || item.initial_label || 'yellow';
}

function createLabelStats(items) {
  const stats = {
    green: 0,
    yellow: 0,
    red: 0,
    gray: 0,
    purple: 0,
    other: 0
  };

  for (const item of items) {
    const label = getLabel(item);
    if (stats[label] == null) {
      stats.other += 1;
    } else {
      stats[label] += 1;
    }
  }

  return stats;
}

function getRawDir(outDir) {
  return path.join(outDir, 'raw');
}

function getReportsDir(outDir) {
  return path.join(outDir, 'reports');
}

function resolveJsonlPath(outDir, fileName) {
  const safeName = path.basename(fileName || '');
  if (!safeName.endsWith('.jsonl')) {
    throw new Error('Invalid JSONL file name.');
  }

  const rawDir = path.resolve(getRawDir(outDir));
  const filePath = path.resolve(rawDir, safeName);
  if (!filePath.startsWith(`${rawDir}${path.sep}`)) {
    throw new Error('JSONL file is outside the output directory.');
  }

  return filePath;
}

async function readJsonlItems(filePath) {
  const content = await fs.readFile(filePath, 'utf8');
  const items = [];

  for (const [index, line] of content.split(/\r?\n/).entries()) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      items.push(JSON.parse(trimmed));
    } catch (error) {
      error.message = `Invalid JSON on line ${index + 1}: ${error.message}`;
      throw error;
    }
  }

  return items;
}

async function listBatches(outDir) {
  const rawDir = getRawDir(outDir);
  await fs.ensureDir(rawDir);
  await fs.ensureDir(getReportsDir(outDir));

  const entries = await fs.readdir(rawDir);
  const jsonlFiles = entries.filter((entry) => entry.toLowerCase().endsWith('.jsonl'));
  const batches = [];

  for (const file of jsonlFiles) {
    const filePath = resolveJsonlPath(outDir, file);
    const stat = await fs.stat(filePath);
    const items = await readJsonlItems(filePath);
    const meta = parseOutputName(file);
    const reportFile = file.replace(/\.jsonl$/i, '.md');
    const reportPath = path.join(getReportsDir(outDir), reportFile);

    batches.push({
      file,
      reportFile: await fs.pathExists(reportPath) ? reportFile : null,
      site: meta.site,
      keyword: meta.keyword,
      timestamp: meta.timestamp,
      modifiedTime: stat.mtime.toISOString(),
      itemCount: items.length,
      labels: createLabelStats(items)
    });
  }

  batches.sort((a, b) => b.modifiedTime.localeCompare(a.modifiedTime));
  return batches;
}

async function getBatchItems(outDir, fileName) {
  const filePath = resolveJsonlPath(outDir, fileName);
  const items = await readJsonlItems(filePath);
  return {
    file: path.basename(fileName),
    items,
    labels: createLabelStats(items)
  };
}

async function getReport(outDir, reportFile) {
  const safeName = path.basename(reportFile || '');
  if (!safeName.endsWith('.md')) {
    throw new Error('Invalid report file name.');
  }

  const reportsDir = path.resolve(getReportsDir(outDir));
  const reportPath = path.resolve(reportsDir, safeName);
  if (!reportPath.startsWith(`${reportsDir}${path.sep}`)) {
    throw new Error('Report file is outside the output directory.');
  }

  return fs.readFile(reportPath, 'utf8');
}

module.exports = {
  getBatchItems,
  getReport,
  listBatches
};
