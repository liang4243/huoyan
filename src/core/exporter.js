const path = require('path');
const fs = require('fs-extra');
const { buildMarkdownReport } = require('../reports/markdown');
const { safeFilePart } = require('./utils');

function parseFormats(formatText) {
  return String(formatText || 'jsonl,md')
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

async function writeJsonl(filePath, items) {
  const content = items.map((item) => JSON.stringify(item)).join('\n');
  await fs.outputFile(filePath, content ? `${content}\n` : '', 'utf8');
}

async function exportItems(items, context) {
  const formats = parseFormats(context.format);
  const site = safeFilePart(context.site);
  const keyword = safeFilePart(context.keyword);
  const baseName = `${site}_${keyword}_${context.timestamp}`;
  const outputBase = context.outDir;
  const outputs = {};

  if (formats.includes('jsonl')) {
    const jsonlPath = path.join(outputBase, 'raw', `${baseName}.jsonl`);
    await writeJsonl(jsonlPath, items);
    outputs.jsonl = jsonlPath;
  }

  if (formats.includes('md') || formats.includes('markdown')) {
    const markdownPath = path.join(outputBase, 'reports', `${baseName}.md`);
    const markdown = buildMarkdownReport(items, context);
    await fs.outputFile(markdownPath, markdown, 'utf8');
    outputs.markdown = markdownPath;
  }

  return outputs;
}

module.exports = {
  exportItems,
  parseFormats
};
