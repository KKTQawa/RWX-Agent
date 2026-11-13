#!/usr/bin/env node
'use strict';
/**
 * Add v2.1 (Stage3 items v3) scores to every full match that already has v2 inputs.
 *
 *   node evaluate/tools/add_v21_scores.js [--root evaluate/output] [--current-only]
 *
 * A match qualifies when it has `stage_1_v2/score.json`, `stage_3/score.json` and an
 * `economy.log` (`prepared/`, `resim/` or `stage_3/`). The tool does not re-run Stage1 and never
 * touches `score_v2.json`; it writes `<match>/score_v21.json` + `score_v21.txt` and the batch report
 * `_v21-summary.json` / `_v21-summary.md` / `_v21-detail.csv`.
 */
const fs = require('node:fs');
const path = require('node:path');
const v21 = require('../score_match_v21');
const {loadConfig, current} = require('../config');

const ROOT = path.resolve(__dirname, '..', '..');
const DEFAULT_OUTPUT = path.join(ROOT, 'evaluate', 'output');
const round = (value, digits = 3) => value == null || !Number.isFinite(value)
  ? null : Number(Number(value).toFixed(digits));
const median = values => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b), middle = sorted.length >> 1;
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};
const mean = values => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
const quantile = (values, p) => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const h = (sorted.length - 1) * p, lo = Math.floor(h), hi = Math.ceil(h);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (h - lo);
};

function matches(root, currentOnly) {
  const found = [];
  function walk(dir) {
    const entries = fs.readdirSync(dir, {withFileTypes: true});
    const has = name => fs.existsSync(path.join(dir, name));
    if (has('stage_1_v2') || has('stage_3/score.json')) { found.push(dir); return; }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      if (['events-live', 'micro', 'prepared', 'replay', 'resim', 'session', 'source-run',
        'stage_1', 'stage_1_v2', 'stage_1_v2_provisional', 'stage_2', 'stage_3', 'stage_3_v21']
        .includes(entry.name)) continue;
      if (currentOnly && entry.name === '_archive') continue;
      walk(path.join(dir, entry.name));
    }
  }
  for (const entry of fs.readdirSync(root, {withFileTypes: true})) {
    if (!entry.isDirectory() || ['micro', 'events-live'].includes(entry.name)) continue;
    if (currentOnly && entry.name === '_archive') continue;
    walk(path.join(root, entry.name));
  }
  return [...new Set(found)].sort();
}

function outcomeOf(dir) {
  for (const name of ['evaluation_v2.json', 'meta.json']) {
    const file = path.join(dir, name);
    if (!fs.existsSync(file)) continue;
    const data = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
    const result = data.result;
    if (result?.outcome) return {outcome: result.outcome, label: result.label || result.outcome};
  }
  return {outcome: 'unknown', label: '未知'};
}

function cutMsOf(dir) {
  const file = path.join(dir, 'evaluation_v2.json');
  if (fs.existsSync(file)) {
    const seconds = JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')).scoreWindowSeconds;
    if (Number.isFinite(seconds)) return Math.round(seconds * 1000);
  }
  const stage3 = JSON.parse(fs.readFileSync(path.join(dir, 'stage_3', 'score.json'), 'utf8'));
  return Number.isFinite(stage3.durationSeconds) ? Math.round(stage3.durationSeconds * 1000) : null;
}

function rowOf(dir, score, root) {
  const stage3 = score.components.stage3;
  const {outcome, label} = outcomeOf(dir);
  const ambush = stage3.ambush, barrage = stage3.barrage;
  return {match: path.basename(dir), relativePath: path.relative(root, dir).replace(/\\/g, '/'),
    archive: score.archive, outcome, label,
    windowSeconds: score.fundsV3.windowSeconds,
    stage1v2: score.components.stage1v2.value,
    ambush: ambush.deduction, barrage: barrage.deduction,
    grinder: stage3.grinder.deduction, fundsV3: stage3.funds.deduction,
    ambushV2: stage3.legacy.ambush.deduction, barrageV2: stage3.legacy.barrage.deduction,
    ambushEvents: ambush.events, ambushAdmitted: ambush.admitted, ambushFast: ambush.fast,
    ambushHits: ambush.hits, ambushAdmittedHits: ambush.admittedHits,
    ambushSaturated: ambush.saturated, ambushLowConfidence: ambush.lowConfidence,
    ambushR: ambush.R, ambushR0: ambush.R0, ambushM: ambush.M,
    barrageEvents: barrage.events, barrageAdmitted: barrage.admitted, barrageDestroyed: barrage.destroyed,
    barrageHits: barrage.hits, barrageAdmittedHits: barrage.admittedHits,
    barrageSaturated: barrage.saturated, barrageLowConfidence: barrage.lowConfidence,
    barrageR: barrage.R, barrageR0: barrage.R0, barrageM: barrage.M,
    stage3V2: stage3.baseTotal, stage3V3: stage3.value,
    totalV2: score.comparison.totalV2, totalV21: score.total, delta: score.comparison.delta,
    funds: {startFunds: score.fundsV3.startFunds, endFunds: score.fundsV3.endFunds,
      initialFunds: score.fundsV3.initialFunds, totalIncome: score.fundsV3.totalIncome,
      totalAvailable: score.fundsV3.totalAvailable, totalSpent: score.fundsV3.totalSpent,
      globalRawRatio: score.fundsV3.globalRawRatio, k: score.fundsV3.k,
      deduction: score.fundsV3.deduction, exponent: score.fundsV3.exponent,
      singleMax: score.fundsV3.singleMax,
      windows: score.fundsV3.windows.map(window => ({k: window.k, raw: window.rawRatio,
        income: window.income, available: window.available, spent: window.spent, seconds: window.seconds}))}};
}

function stats(rows) {
  if (!rows.length) return {matches: 0};
  const totals = rows.map(row => row.totalV21);
  const before = rows.map(row => row.totalV2).filter(Number.isFinite);
  const deltas = rows.map(row => row.delta).filter(Number.isFinite);
  const stage3v3 = rows.map(row => row.stage3V3);
  const stage3v2 = rows.map(row => row.stage3V2).filter(Number.isFinite);
  return {matches: rows.length,
    totalV21: {mean: round(mean(totals)), median: round(median(totals)),
      min: round(Math.min(...totals)), max: round(Math.max(...totals)),
      positive: totals.filter(value => value > 0).length},
    totalV2: {mean: round(mean(before)), median: round(median(before)),
      min: round(Math.min(...before)), max: round(Math.max(...before)),
      positive: before.filter(value => value > 0).length},
    stage3: {v2Mean: round(mean(stage3v2)), v3Mean: round(mean(stage3v3)),
      v3Median: round(median(stage3v3)), v3Min: round(Math.min(...stage3v3)),
      v3Max: round(Math.max(...stage3v3))},
    delta: {mean: round(mean(deltas)), min: round(Math.min(...deltas)), max: round(Math.max(...deltas)),
      improved: deltas.filter(value => value > 0).length, worsened: deltas.filter(value => value < 0).length,
      unchanged: deltas.filter(value => value === 0).length},
    ambush: {mean: round(mean(rows.map(row => row.ambush))), v2Mean: round(mean(rows.map(row => row.ambushV2))),
      events: rows.reduce((sum, row) => sum + row.ambushEvents, 0),
      admitted: rows.reduce((sum, row) => sum + row.ambushAdmitted, 0),
      hits: rows.reduce((sum, row) => sum + row.ambushHits, 0),
      admittedHits: rows.reduce((sum, row) => sum + row.ambushAdmittedHits, 0),
      saturated: rows.reduce((sum, row) => sum + row.ambushSaturated, 0),
      lowConfidence: rows.filter(row => row.ambushLowConfidence).length},
    barrage: {mean: round(mean(rows.map(row => row.barrage))), v2Mean: round(mean(rows.map(row => row.barrageV2))),
      events: rows.reduce((sum, row) => sum + row.barrageEvents, 0),
      admitted: rows.reduce((sum, row) => sum + row.barrageAdmitted, 0),
      hits: rows.reduce((sum, row) => sum + row.barrageHits, 0),
      admittedHits: rows.reduce((sum, row) => sum + row.barrageAdmittedHits, 0),
      destroyed: rows.reduce((sum, row) => sum + row.barrageDestroyed, 0),
      saturated: rows.reduce((sum, row) => sum + row.barrageSaturated, 0),
      lowConfidence: rows.filter(row => row.barrageLowConfidence).length}};
}

function table(headers, rows) {
  return [`| ${headers.join(' | ')} |`, `|${headers.map(() => '---').join('|')}|`,
    ...rows.map(row => `| ${row.join(' | ')} |`)].join('\n');
}
const num = (value, digits = 3) => Number.isFinite(value) ? Number(value).toFixed(digits) : '—';
const signed = value => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(3)}` : '—';
const cell = value => String(value ?? '').replace(/\|/g, '\\|');
const pair = (a, b) => `${num(a)}→${num(b)}`;

function markdown(summary) {
  const current = summary.rows.filter(row => row.archive === 'current');
  const archive = summary.rows.filter(row => row.archive !== 'current');
  const out = ['# 完整对局 v2.1 评分汇总（Stage3 items v3）', '',
    `生成时间：${summary.generatedAt}`,
    `公式：\`stage3-v2.1 = max(0, 100 − 偷袭v3 − 偷家v3 − 绞肉机 − 资金v3)\`，` +
      `\`total-v2.1 = clip(stage1-v2 × ${summary.weights.stage1} + stage3-v2.1 × ${summary.weights.stage3}, ` +
      `${summary.clip[0]}, ${summary.clip[1]})\``, '',
    '偷袭 v3：我方陆地移动单位被敌方移动单位打的 idle 事件都进 M1（含 T<T0 的快速反应和一击死亡）；' +
      '`R1 = Σ w·u′·sev / (M1 + 3)`，`扣分 = 50·(1−e^(−R1/R0₁))`。',
    '偷家 v3：炮兵缓冲事件（N≥2 或摧毁）都进 M2；`T_j` 取第一次到最后一发（摧毁取摧毁时刻），' +
      '`R2 = Σ w·u′·sev / (M2 + 2)`，`扣分 = 40·(1−e^(−R2/R0₂))`。',
    `参数：α=0.4、δ=0.2、s_lo=0.3、偷袭 ε=5%/T0=3s/T_hi=${num(summary.calibration.ambushThi)}、` +
      `偷家 ε=3%/T0=8s/T_hi=${num(summary.calibration.barrageThi)}；` +
      `R0 取基线 R 中位数：偷袭 ${num(summary.calibration.ambushR0, 6)}、偷家 ${num(summary.calibration.barrageR0, 6)}。`, '',
    `## 当前批（${current.length} 局）`, ''];
  out.push(table(['#', '对局', '窗口s', '结局', 'Stage1-v2', '偷袭v3', '偷家v3', '绞肉机', '资金v3',
    'Stage3-v3', '总分v2', '总分v2.1', 'Δ'], current.map((row, index) => [index + 1,
    cell(row.match), num(row.windowSeconds, 1), row.label, num(row.stage1v2), num(row.ambush),
    num(row.barrage), num(row.grinder), num(row.fundsV3), num(row.stage3V3), num(row.totalV2),
    num(row.totalV21), signed(row.delta)])));
  out.push('', '## 偷袭 / 偷家 v2→v3', '',
    '`事件` 是准入/总记录；`饱和` 是 T≥T_hi 的准入事件数。v2 列是伤害占比版，只作对照，不计分。', '');
  out.push(table(['#', '对局', '偷袭v2→v3', '偷袭事件(准入/总)', '偷袭M', '偷袭R1', '偷袭饱和',
    '偷家v2→v3', '偷家事件(准入/总)', '偷家M', '偷家R2', '偷家饱和'],
    current.map((row, index) => [index + 1, cell(row.match), pair(row.ambushV2, row.ambush),
      `${row.ambushAdmitted}/${row.ambushEvents}`, num(row.ambushM), num(row.ambushR, 6),
      `${row.ambushSaturated}/${row.ambushAdmitted}`, pair(row.barrageV2, row.barrage),
      `${row.barrageAdmitted}/${row.barrageEvents}`, num(row.barrageM), num(row.barrageR, 6),
      `${row.barrageSaturated}/${row.barrageAdmitted}`])));
  const s = summary.stats.current;
  out.push('', '## 统计（当前批）', '',
    table(['指标', 'v2', 'v2.1-v3'], [
      ['总分均值', num(s.totalV2.mean), num(s.totalV21.mean)],
      ['总分中位数', num(s.totalV2.median), num(s.totalV21.median)],
      ['总分最低', num(s.totalV2.min), num(s.totalV21.min)],
      ['总分最高', num(s.totalV2.max), num(s.totalV21.max)],
      ['Stage3 均值', num(s.stage3.v2Mean), num(s.stage3.v3Mean)],
      ['偷袭扣分均值', num(s.ambush.v2Mean), num(s.ambush.mean)],
      ['偷家扣分均值', num(s.barrage.v2Mean), num(s.barrage.mean)]]), '',
    `Δ 总分：均 ${signed(s.delta.mean)}，区间 [${signed(s.delta.min)}, ${signed(s.delta.max)}]；` +
      `升高 ${s.delta.improved} 局、降低 ${s.delta.worsened} 局、不变 ${s.delta.unchanged} 局。`, '',
    `v3 事件：偷袭 ${s.ambush.admitted}/${s.ambush.events} 准入、命中 ${s.ambush.admittedHits}/${s.ambush.hits}，` +
      `饱和 ${s.ambush.saturated}，低置信 ${s.ambush.lowConfidence} 局；偷家 ${s.barrage.admitted}/${s.barrage.events} ` +
      `准入、命中 ${s.barrage.admittedHits}/${s.barrage.hits}（摧毁 ${s.barrage.destroyed}），` +
      `饱和 ${s.barrage.saturated}，低置信 ${s.barrage.lowConfidence} 局。`, '',
    `T_hi：偷袭 ${num(summary.calibration.ambushThi)} s、偷家 ${num(summary.calibration.barrageThi)} s` +
      `（26 局逐局准入事件 T 的 P90 的中位数）；R0：${num(summary.calibration.ambushR0, 6)} / ` +
      `${num(summary.calibration.barrageR0, 6)}（26 局 R 的中位数）。`, '');
  if (archive.length) {
    out.push(`## 归档局（${archive.length} 局，历史批次参数，只作参考）`, '',
      '归档局的 Stage1/Stage3 是历史批次算的；两列都用当前总分公式重算，不使用归档 `score_v2.json` 的旧公式。', '');
    out.push(table(['#', '对局', '批次', '窗口s', 'Stage1-v2', 'Stage3-v3', '总分v2', '总分v2.1', 'Δ'],
      archive.map((row, index) => [index + 1, cell(row.match), row.archive, num(row.windowSeconds, 1),
        num(row.stage1v2), num(row.stage3V3), num(row.totalV2), num(row.totalV21), signed(row.delta)])));
    out.push('');
  }
  return out.join('\n');
}

function csv(rows) {
  const header = ['match', 'relativePath', 'archive', 'outcome', 'windowSeconds', 'stage1v2',
    'ambushV3', 'ambushV2', 'ambushEvents', 'ambushAdmitted', 'ambushHits', 'ambushAdmittedHits',
    'ambushFast', 'ambushSaturated', 'ambushM', 'ambushR', 'ambushR0', 'barrageV3', 'barrageV2',
    'barrageEvents', 'barrageAdmitted', 'barrageHits', 'barrageAdmittedHits', 'barrageDestroyed',
    'barrageSaturated', 'barrageM', 'barrageR', 'barrageR0', 'grinder', 'fundsV3',
    'stage3V2', 'stage3V3', 'totalV2', 'totalV21', 'delta', 'k', 'fundsDeduction'];
  const quote = value => `"${String(value ?? '').replace(/"/g, '""')}"`;
  return [header.join(','), ...rows.map(row => [row.match, row.relativePath, row.archive, row.outcome,
    row.windowSeconds, row.stage1v2, row.ambush, row.ambushV2, row.ambushEvents, row.ambushAdmitted,
    row.ambushHits, row.ambushAdmittedHits, row.ambushFast, row.ambushSaturated, row.ambushM,
    row.ambushR, row.ambushR0, row.barrage, row.barrageV2, row.barrageEvents, row.barrageAdmitted,
    row.barrageHits, row.barrageAdmittedHits, row.barrageDestroyed, row.barrageSaturated, row.barrageM,
    row.barrageR, row.barrageR0, row.grinder, row.fundsV3, row.stage3V2, row.stage3V3, row.totalV2,
    row.totalV21, row.delta, row.funds.k, row.funds.deduction].map(quote).join(','))].join('\n') + '\n';
}

async function main(argv = process.argv) {
  const args = argv.slice(2);
  let root = DEFAULT_OUTPUT, currentOnly = false;
  while (args.length) {
    const flag = args.shift();
    if (flag === '--root') root = path.resolve(args.shift());
    else if (flag === '--current-only') currentOnly = true;
    else throw Error('Usage: node evaluate/tools/add_v21_scores.js [--root <dir>] [--current-only]');
  }
  const rows = [], ignored = [];
  for (const dir of matches(root, currentOnly)) {
    try {
      const cutMs = cutMsOf(dir);
      rows.push(rowOf(dir, await v21.main(['node', 'score_match_v21.js', dir, '--quiet',
        ...(Number.isFinite(cutMs) ? ['--cut-ms', String(cutMs)] : [])]), root));
    } catch (error) {
      ignored.push({match: path.basename(dir), relativePath: path.relative(root, dir).replace(/\\/g, '/'),
        reason: error.message});
    }
  }
  const order = (a, b) => (a.archive === 'current' ? 0 : 1) - (b.archive === 'current' ? 0 : 1) ||
    (b.totalV21 - a.totalV21) || String(a.match).localeCompare(String(b.match));
  rows.sort(order);
  const currentRows = rows.filter(row => row.archive === 'current');
  const config = loadConfig();
  const summary = {schema: 1, version: 'v21-summary-v4', generatedAt: new Date().toISOString(),
    stage3Version: config.stage3.versionV21,
    weights: {stage1: v21.STAGE1_WEIGHT, stage3: v21.STAGE3_WEIGHT},
    clip: [v21.CLIP_MIN, v21.CLIP_MAX],
    caps: {ambush: current('stage3.v21.parameters.ambushV3.P_max', config),
      barrage: current('stage3.v21.parameters.barrageV3.P_max', config)},
    formula: 'stage3v2.1 = max(0, 100 - ambushV3 - barrageV3 - grinder - fundsV3); ' +
      'total = clip(stage1v2 * stage1Weight + stage3v21 * stage3Weight, clipMin, clipMax)',
    scope: {root: path.relative(ROOT, root).replace(/\\/g, '/') || '.', currentOnly},
    calibration: {
      ambushRMedian: round(median(currentRows.map(row => row.ambushR)), 6),
      barrageRMedian: round(median(currentRows.map(row => row.barrageR)), 6),
      ambushR0: current('stage3.v21.parameters.ambushV3.R0', config),
      barrageR0: current('stage3.v21.parameters.barrageV3.R0', config),
      ambushThi: current('stage3.v21.parameters.ambushV3.T_hi', config),
      barrageThi: current('stage3.v21.parameters.barrageV3.T_hi', config)},
    stats: {current: stats(currentRows)}, rows, ignored};
  fs.writeFileSync(path.join(root, '_v21-summary.json'), JSON.stringify(summary, null, 2) + '\n');
  fs.writeFileSync(path.join(root, '_v21-summary.md'), markdown(summary) + '\n');
  fs.writeFileSync(path.join(root, '_v21-detail.csv'), csv(rows));
  const count = summary.stats.current;
  console.log(`v2.1-v3: ${count.matches} current + ${rows.length - count.matches} archived, ` +
    `${ignored.length} ignored; total mean ${count.totalV2.mean} -> ${count.totalV21.mean}`);
  return summary;
}

if (require.main === module) main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
module.exports = {matches, stats, markdown, csv, main};
