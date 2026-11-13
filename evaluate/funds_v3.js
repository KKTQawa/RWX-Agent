'use strict';
/**
 * 资金空余 v3（`score_design.md` 第三阶段 §4.1）。
 *
 * 把评分窗口按游戏时长切成三段：`[0, 1/4)`、`[1/4, 3/4)`、`[3/4, 1]`。每段分别算
 *
 *   K_i = 该段总花费 / 该段总收入
 *   K   = 0.4·K_1 + 0.4·K_2 + 0.2·K_3
 *   S   = (1 − K)^0.5 × SingleMax
 *
 * 收入按“每段都有自己的初始资金”的口径：每一段的分母 = **段初资金 + 段内每秒收入**。
 * 第一段的段初资金就是开局 4000；第二、三段的段初资金是上一段结束时剩下的余额。每段花费仍取
 * 资金余额恒等式：
 *
 *   段收入/可用 = 段初资金 + Σ 段内每秒收入字段 × `incomeFieldPerSecond`
 *   段花费     = 段初资金 + 段内现金收入 − 段尾资金
 *
 * 因此 `K_i = 1 − 段尾资金 / 段可用`，天然落在 [0,1]；整窗口同理
 * `总花费 / 总可用 = 1 − 结束资金 / (开局资金 + 总收入)`。
 */
const VERSION = 'funds-v3-v4';
const DEFAULTS = Object.freeze({incomeFieldPerSecond: 1.5625, singleMax: 30, exponent: 0.5,
  windowSplits: [0.25, 0.75], windowWeights: [0.4, 0.4, 0.2]});
const round = (value, digits = 3) => Number(value.toFixed(digits));
const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
const rateOf = (row, incomeFieldPerSecond) => Number.isFinite(row.incomePerSecond)
  ? row.incomePerSecond : Number(row.incomeField) * incomeFieldPerSecond;

function fundsV3(samples, options = {}) {
  const incomeFieldPerSecond = Number(options.incomeFieldPerSecond ?? DEFAULTS.incomeFieldPerSecond);
  const singleMax = Number(options.singleMax ?? DEFAULTS.singleMax);
  const exponent = Number(options.exponent ?? DEFAULTS.exponent);
  const windowSplits = (options.windowSplits ?? DEFAULTS.windowSplits).map(Number);
  const windowWeights = (options.windowWeights ?? DEFAULTS.windowWeights).map(Number);
  if (windowSplits.length !== 2 || windowWeights.length !== 3)
    throw Error('funds v3 needs two split points and three window weights');
  if (!(exponent > 0)) throw Error('funds v3 needs a positive exponent');
  if (!Array.isArray(samples) || samples.length < 2)
    return {version: VERSION, available: false, reason: 'ECONOMY_SAMPLES_MISSING', singleMax,
      exponent, incomeFieldPerSecond, windowSplits, windowWeights, deduction: 0};
  for (let index = 0; index < samples.length; index++) {
    const row = samples[index];
    if (row.second !== index || !Number.isFinite(row.funds) || !Number.isFinite(rateOf(row, incomeFieldPerSecond)))
      throw Error('Invalid per-second economy evidence');
  }
  const initialFunds = samples[0].funds;
  const span = samples.length - 1;
  const first = Math.floor(span * windowSplits[0]);
  const second = Math.floor(span * windowSplits[1]);
  const bounds = [[0, first], [first, second], [second, span]];
  let totalIncome = 0, negativeDeltaSpend = 0, positivePerSecondSpend = 0;
  for (let index = 1; index < samples.length; index++) {
    const rate = rateOf(samples[index], incomeFieldPerSecond), delta = samples[index].funds - samples[index - 1].funds;
    totalIncome += rate;
    if (delta < 0) negativeDeltaSpend -= delta;
    if (rate - delta > 0) positivePerSecondSpend += rate - delta;
  }
  const windows = bounds.map(([start, end], index) => {
    let income = 0;
    for (let cursor = start + 1; cursor <= end; cursor++) income += rateOf(samples[cursor], incomeFieldPerSecond);
    // Every window has its own opening balance: the first one is the match's 4000, later ones are
    // the balance carried over from the previous window.
    const openingFunds = samples[start].funds;
    const available = openingFunds + income;
    const spent = available - samples[end].funds;
    const rawRatio = available > 0 ? spent / available : null;
    const exempt = !(available > 0);
    return {index: index + 1, startSecond: start, endSecond: end, seconds: end - start,
      startFunds: round(openingFunds), endFunds: round(samples[end].funds),
      income: round(income), available: round(available), spent: round(spent),
      rawRatio: rawRatio == null ? null : round(rawRatio, 4),
      k: exempt ? 1 : round(clamp(rawRatio, 0, 1), 4), exempt};
  });
  const ratio = windows.reduce((sum, window, index) => sum + windowWeights[index] * window.k, 0);
  const k = round(clamp(ratio, 0, 1), 4);
  const totalAvailable = initialFunds + totalIncome;
  const globalSpent = Math.max(0, totalAvailable - samples[samples.length - 1].funds);
  return {version: VERSION, available: true, samples: samples.length, windowSeconds: span,
    initialFunds: round(initialFunds), startFunds: round(initialFunds),
    endFunds: round(samples[samples.length - 1].funds),
    totalIncome: round(totalIncome), totalAvailable: round(totalAvailable), totalSpent: round(globalSpent),
    globalRawRatio: totalAvailable > 0 ? round(globalSpent / totalAvailable, 4) : null,
    globalK: totalAvailable > 0 ? round(clamp(globalSpent / totalAvailable, 0, 1), 4) : 0,
    windowSplits, windowWeights, windows, k, ratio: round(ratio, 4), singleMax, exponent,
    deduction: round(singleMax * Math.pow(Math.max(0, 1 - k), exponent)),
    incomeFieldPerSecond,
    diagnostics: {negativeDeltaSpend: round(negativeDeltaSpend),
      positivePerSecondSpend: round(positivePerSecondSpend)}};
}

module.exports = {VERSION, DEFAULTS, fundsV3};
