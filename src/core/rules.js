const { clamp } = require('./utils');

const RISK_KEYWORDS = [
  '仅通电',
  '不退不换',
  '维修',
  '故障',
  '尸体',
  '暗病',
  '进水',
  '锁机',
  '账号',
  '监管机',
  '无测试',
  '懂的来',
  '拆修',
  '主板坏',
  '屏幕坏',
  '不包好坏'
];

const POSITIVE_KEYWORDS = [
  '支持自提',
  '支持验货',
  '个人闲置',
  '实拍',
  '功能正常',
  '测试正常',
  '原装配件',
  '箱说全',
  '当面试机',
  '可试机',
  '正常使用'
];

function findMatchedKeywords(text, keywords) {
  return keywords.filter((keyword) => text.includes(keyword));
}

function buildRuleReason({ riskFlags, positiveFlags, hasReferencePrice, referencePrice, item, isSuspiciousLowPrice, isBelowMarket }) {
  const parts = [
    `本地规则初筛：风险词 ${riskFlags.length} 个，加分词 ${positiveFlags.length} 个`
  ];

  if (hasReferencePrice && item.price != null) {
    parts.push(`参考价 ${referencePrice}，当前价 ${item.price}`);
    if (isSuspiciousLowPrice) parts.push('价格低于参考价 60%，仅标记疑似神价，需要人工或 AI 强验证');
    else if (isBelowMarket) parts.push('价格低于参考价 80%');
  }

  if (riskFlags.length) parts.push(`风险词：${riskFlags.join('、')}`);
  if (positiveFlags.length) parts.push(`加分词：${positiveFlags.join('、')}`);

  return parts.join('；');
}

function applyRules(item, options = {}) {
  const referencePrice = Number(options.referencePrice);
  const hasReferencePrice = Number.isFinite(referencePrice) && referencePrice > 0;
  const text = `${item.title} ${item.desc}`;
  const riskFlags = findMatchedKeywords(text, RISK_KEYWORDS);
  const positiveFlags = findMatchedKeywords(text, POSITIVE_KEYWORDS);

  let ruleScore = 60;
  ruleScore -= riskFlags.length * 10;
  ruleScore += positiveFlags.length * 5;

  let isSuspiciousLowPrice = false;
  let isBelowMarket = false;
  if (hasReferencePrice && item.price != null) {
    if (item.price < referencePrice * 0.6) {
      isSuspiciousLowPrice = true;
      riskFlags.push('价格异常低，需要强验证');
    } else if (item.price < referencePrice * 0.8) {
      isBelowMarket = true;
      ruleScore += 10;
    }
  }

  ruleScore = clamp(ruleScore, 0, 100);

  let ruleLabel = 'yellow';
  if (isSuspiciousLowPrice) {
    ruleLabel = 'purple';
  } else if (riskFlags.length > 0 && ruleScore <= 50) {
    ruleLabel = 'red';
  } else if (riskFlags.length > 0) {
    ruleLabel = 'yellow';
  } else if (ruleScore >= 75) {
    ruleLabel = 'green';
  } else if (ruleScore >= 55) {
    ruleLabel = 'yellow';
  } else {
    ruleLabel = 'gray';
  }

  const ruleReason = buildRuleReason({
    riskFlags,
    positiveFlags,
    hasReferencePrice,
    referencePrice,
    item,
    isSuspiciousLowPrice,
    isBelowMarket
  });

  return {
    ...item,
    risk_flags: riskFlags,
    positive_flags: positiveFlags,
    rule_label: ruleLabel,
    rule_score: ruleScore,
    rule_reason: ruleReason,
    scoring_method: 'local_keyword_rules_v1',
    needs_ai_review: true,
    ai_label: null,
    ai_score: null,
    ai_reason: '',
    ai_questions: [],
    // Backward-compatible aliases. Treat these as local-rule output, not final AI judgment.
    initial_label: ruleLabel,
    score: ruleScore
  };
}

module.exports = {
  POSITIVE_KEYWORDS,
  RISK_KEYWORDS,
  applyRules
};
