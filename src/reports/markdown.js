const { truncate } = require('../core/utils');

function escapeTableCell(value) {
  return String(value == null ? '' : value)
    .replace(/\r?\n/g, ' ')
    .replace(/\|/g, '\\|')
    .trim();
}

function linkCell(label, url) {
  if (!url) return '';
  return `[${escapeTableCell(label)}](${url})`;
}

function getRuleLabel(item) {
  return item.rule_label || item.initial_label || 'yellow';
}

function getRuleScore(item) {
  return item.rule_score == null ? item.score : item.rule_score;
}

function countByRuleLabel(items) {
  const stats = {
    green: 0,
    yellow: 0,
    red: 0,
    gray: 0,
    purple: 0
  };

  for (const item of items) {
    const label = getRuleLabel(item);
    if (stats[label] == null) stats[label] = 0;
    stats[label] += 1;
  }

  return stats;
}

function buildMarkdownReport(items, context) {
  const stats = countByRuleLabel(items);
  const lines = [];

  lines.push('# 商品采集报告');
  lines.push('');
  lines.push('> 注意：规则标签和规则分是本地关键词规则的机械初筛，不是 AI 最终判断。建议把本报告交给 AI 做二次筛选、风险解释和排序。');
  lines.push('');
  lines.push(`- 搜索关键词：${context.keyword || ''}`);
  lines.push(`- 来源网站：${context.site || ''}`);
  lines.push(`- 提取时间：${context.extractTime || ''}`);
  lines.push(`- 商品总数：${items.length}`);
  lines.push(`- 规则标签统计：green ${stats.green} / yellow ${stats.yellow} / red ${stats.red} / gray ${stats.gray} / purple ${stats.purple}`);
  lines.push(`- 评分方法：local_keyword_rules_v1`);
  lines.push('');
  lines.push('## 给 AI 的复核任务');
  lines.push('');
  lines.push('请不要把“规则标签/规则分”当成最终结论。请结合标题、简介、价格、卖家、地区、风险词、加分词、链接和图片 URL，重新判断：');
  lines.push('');
  lines.push('- 是否疑似配件冒充整机、标题党、异常低价或描述矛盾。');
  lines.push('- 是否值得继续沟通、自提验机或直接跳过。');
  lines.push('- 给出推荐排序、风险解释、需要问卖家的问题。');
  lines.push('');
  lines.push('| 编号 | 规则标签 | 规则分 | 标题 | 价格 | 地区 | 风险词 | 加分词 | 简介 | 规则原因 | 链接 | 图片URL | AI复核 |');
  lines.push('|---|---:|---:|---|---:|---|---|---|---|---|---|---|---|');

  for (const item of items) {
    lines.push([
      escapeTableCell(item.id),
      escapeTableCell(getRuleLabel(item)),
      escapeTableCell(getRuleScore(item)),
      escapeTableCell(item.title),
      escapeTableCell(item.price_raw),
      escapeTableCell(item.location),
      escapeTableCell((item.risk_flags || []).join(', ')),
      escapeTableCell((item.positive_flags || []).join(', ')),
      escapeTableCell(truncate(item.desc, 80)),
      escapeTableCell(truncate(item.rule_reason || '', 120)),
      linkCell('打开', item.url),
      linkCell('图片', item.image_url),
      escapeTableCell(item.ai_label || '待复核')
    ].join(' | ').replace(/^/, '| ').replace(/$/, ' |'));
  }

  lines.push('');
  return lines.join('\n');
}

module.exports = {
  buildMarkdownReport
};
