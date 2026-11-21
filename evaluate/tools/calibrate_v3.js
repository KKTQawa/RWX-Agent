#!/usr/bin/env node
'use strict';
/**
 * 第三阶段 v3（偷袭 / 偷家）的全局参数标定：`T_hi` 与 `R0`。
 *
 * 每一局都用同一组全局参数计分（`stage3.v21.parameters.ambushV3/barrageV3`），所以“让某一类
 * 对局的参数也影响另一类”只有一条路：把那一类对局纳入标定池，重算这两个数并写回 `config.json`，
 * 然后整批重跑。本工具按池给出候选值，并**用同一批记录重算**每局的扣分变化，`--write` 才落盘。
 *
 *   node evaluate/tools/calibrate_v3.js                  # 只报告（默认池 current）
 *   node evaluate/tools/calibrate_v3.js --pool ai       # 只用 AI 对局
 *   node evaluate/tools/calibrate_v3.js --pool human    # 只用人类对局
 *   node evaluate/tools/calibrate_v3.js --pool archive  # 含归档
 *   node evaluate/tools/calibrate_v3.js --pool ai --write
 *
 * 口径（与 2026-11-12 那次一致）：`T_hi` = 各局准入事件 T 的 P90，再取池内中位数；`R0` = 池内各局
 * R 的中位数。`R` 与 `S0` 无关，所以改完可以直接复算扣分，不必重跑对局。
 */
const fs = require('node:fs');
const path = require('node:path');
const {loadConfig, current} = require('../config');

const ROOT = path.resolve(__dirname, '..', '..');
const OUTPUT = path.join(ROOT, 'evaluate', 'output');
const CONFIG_FILE = path.join(ROOT, 'evaluate', 'config.json');
const round = (value, digits = 3) => value == null || !Number.isFinite(Number(value))
  ? null : Number(Number(value).toFixed(digits));
const clip = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
const median = values => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b), middle = sorted.length >> 1;
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};

function findMatches() {
  const found = [];
  for (const entry of fs.readdirSync(OUTPUT, {withFileTypes: true})) {
    if (!entry.isDirectory() || ['micro', 'events-live'].includes(entry.name)) continue;
    const root = path.join(OUTPUT, entry.name);
    if (entry.name === '_archive') {
      for (const archive of fs.readdirSync(root, {withFileTypes: true})) {
        if (!archive.isDirectory()) continue;
        for (const match of fs.readdirSync(path.join(root, archive.name), {withFileTypes: true})) {
          if (match.isDirectory()) found.push(path.join(root, archive.name, match.name));
        }
      }
      continue;
    }
    found.push(root);
  }
  return found.filter(dir => fs.existsSync(path.join(dir, 'score_v21.json')));
}

function readScore(dir) {
  const score = JSON.parse(fs.readFileSync(path.join(dir, 'score_v21.json'), 'utf8').replace(/^\uFEFF/, ''));
  const stage3 = score.components?.stage3;
  // Archive files from before items-v3 have no ambush/barrage blocks; they cannot join a pool.
  if (!stage3 || !stage3.ambush || !stage3.barrage) return null;
  return {dir, name: path.basename(dir), human: path.basename(dir).endsWith('_human'),
    stage1: Number(score.components.stage1v2?.value) || 0, totalV21: Number(score.total),
    stage3: Number(stage3.value), ambush: stage3.ambush, barrage: stage3.barrage,
    grinder: Number(stage3.grinder?.deduction) || 0, funds: Number(stage3.funds?.deduction) || 0};
}

const POOLS = {
  ai: angle => !angle.human && !angle.archive,
  human: angle => angle.human,
  current: angle => !angle.archive,
  archive: angle => angle.archive,
  all: () => true,
};

function select(rows, pool) {
  const keep = POOLS[pool];
  if (!keep) throw Error(`unknown pool ${pool}`);
  return rows.filter(row => keep({human: row.human, archive: row.archive}));
}

function rescore(records, params, T_hi, R0) {
  let M = 0, numerator = 0;
  for (const record of records || []) {
    const T = Math.max(0, Number(record.T) || 0);
    const u = clip((Math.log1p(T) - Math.log1p(params.T0)) / (Math.log1p(T_hi) - Math.log1p(params.T0)), 0, 1);
    const uPrime = Math.min(1, u + params.delta * (record.died || record.destroyed ? 1 : 0));
    const sev = Number(record.sev);
    const w = Number(record.w);
    if (!Number.isFinite(w)) continue;
    M += w; numerator += w * uPrime * sev;
  }
  const R = M > 0 ? numerator / (M + params.W_floor) : 0;
  return {R: round(R, 6), deduction: round(params.P_max * (1 - Math.exp(-R / R0)))};
}

function calibrate(rows) {
  const ambushThi = median(rows.map(row => row.ambush.tP90).filter(value => Number.isFinite(value) && value > 0));
  const barrageThi = median(rows.map(row => row.barrage.tP90).filter(value => Number.isFinite(value) && value > 0));
  const ambushR0 = median(rows.map(row => Number(row.ambush.R) || 0));
  const barrageR0 = median(rows.map(row => Number(row.barrage.R) || 0));
  return {matches: rows.length, ambushThi: round(ambushThi, 3), barrageThi: round(barrageThi, 3),
    ambushR0: round(ambushR0, 6), barrageR0: round(barrageR0, 6)};
}

function apply(rows, candidate) {
  const config = loadConfig();
  const a = current('stage3.v21.parameters.ambushV3', config);
  const b = current('stage3.v21.parameters.barrageV3', config);
  let before = 0, after = 0, totalBefore = 0, totalAfter = 0;
  const perMatch = [];
  for (const row of rows) {
    const ambush = rescore(row.ambush.records, a, candidate.ambushThi, candidate.ambushR0);
    const barrage = rescore(row.barrage.records, b, candidate.barrageThi, candidate.barrageR0);
    const stage3Before = 100 - (row.ambush.deduction + row.barrage.deduction + row.grinder + row.funds);
    const stage3After = 100 - (ambush.deduction + barrage.deduction + row.grinder + row.funds);
    before += row.ambush.deduction + row.barrage.deduction;
    after += ambush.deduction + barrage.deduction;
    totalBefore += row.totalV21;
    const total = clip(row.stage1 * 0.4 + Math.max(0, stage3After) * 0.6, 0, 100);
    totalAfter += total;
    perMatch.push({name: row.name, ambushBefore: row.ambush.deduction, ambushAfter: ambush.deduction,
      barrageBefore: row.barrage.deduction, barrageAfter: barrage.deduction,
      stage3Before: round(stage3Before), stage3After: round(stage3Max(stage3After)),
      totalBefore: row.totalV21, totalAfter: round(total, 2)});
  }
  return {pool: rows.length, ambushPlusBarrage: {before: round(before), after: round(after)},
    total: {before: round(totalBefore), after: round(totalAfter)}, perMatch};
}
function stage3Max(value) { return Math.max(0, value); }

function persist(candidate, pool) {
  const config = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8').replace(/^\uFEFF/, ''));
  const timestamp = new Date().toISOString();
  config.updatedAt = timestamp;
  config.stage3.v21.parameters.ambushV3.T_hi.current = candidate.ambushThi;
  config.stage3.v21.parameters.ambushV3.R0.current = candidate.ambushR0;
  config.stage3.v21.parameters.barrageV3.T_hi.current = candidate.barrageThi;
  config.stage3.v21.parameters.barrageV3.R0.current = candidate.barrageR0;
  config.stage3.v21.calibration = {
    source: `calibrate_v3.js pool=${pool}, ${candidate.matches} matches`,
    matches: candidate.matches,
    tHi: {ambush: candidate.ambushThi, barrage: candidate.barrageThi,
      method: 'median of per-match admitted-event T P90 values'},
    r0: {ambush: candidate.ambushR0, barrage: candidate.barrageR0,
      method: 'median of per-match R values'},
    pool};
  fs.writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2) + '\n', 'utf8');
  return timestamp;
}

function main(argv = process.argv) {
  const args = argv.slice(2);
  const options = {pool: 'current', write: false, json: null, root: OUTPUT};
  while (args.length) {
    const flag = args.shift();
    if (flag === '--pool') options.pool = args.shift();
    else if (flag === '--write') options.write = true;
    else if (flag === '--json') options.json = path.resolve(args.shift());
    else if (flag === '--root') options.root = path.resolve(args.shift());
    else throw Error('Usage: node evaluate/tools/calibrate_v3.js [--pool ai|human|current|archive|all] [-'
      + '-write] [--json <file>]');
  }
  const rows = findMatches().map(dir => {
    const score = readScore(dir);
    return score && {...score, archive: path.relative(OUTPUT, dir).replace(/\\/g, '/').startsWith('_archive/')};
  }).filter(Boolean);
  const pools = options.pool === 'all' ? ['ai', 'human', 'current', 'all'] : [options.pool];
  const report = {generatedAt: new Date().toISOString(), pools: {}, current: {
    ambushThi: current('stage3.v21.parameters.ambushV3.T_hi'),
    ambushR0: current('stage3.v21.parameters.ambushV3.R0'),
    barrageThi: current('stage3.v21.parameters.barrageV3.T_hi'),
    barrageR0: current('stage3.v21.parameters.barrageV3.R0')}};
  for (const pool of pools) {
    const selected = select(rows, pool);
    if (selected.length < 3) { report.pools[pool] = {matches: selected.length, skipped: true}; continue; }
    const candidate = calibrate(selected);
    report.pools[pool] = {...candidate, impact: apply(selected, candidate)};
  }
  const target = report.pools[options.pool];
  if (options.write) {
    if (!target || target.skipped) throw Error(`pool ${options.pool} has too few matches to write`);
    report.written = persist(target, options.pool);
  }
  if (options.json) {
    fs.mkdirSync(path.dirname(options.json), {recursive: true});
    fs.writeFileSync(options.json, JSON.stringify(report, null, 2) + '\n');
  }
  console.log(`当前：T_hi ${report.current.ambushThi} / ${report.current.barrageThi}；`
    + `R0 ${report.current.ambushR0} / ${report.current.barrageR0}`);
  for (const pool of Object.keys(report.pools)) {
    const entry = report.pools[pool];
    if (entry.skipped) { console.log(`${pool}: 仅 ${entry.matches} 局，跳过`); continue; }
    console.log(`${pool}: ${entry.matches} 局 → T_hi ${entry.ambushThi} / ${entry.barrageThi}；`
      + `R0 ${entry.ambushR0} / ${entry.barrageR0}；`
      + `偷袭+偷家扣分 ${entry.impact.ambushPlusBarrage.before} → ${entry.impact.ambushPlusBarrage.after}；`
      + `总分合计 ${entry.impact.total.before} → ${entry.impact.total.after}`);
  }
  if (report.written) console.log(`written ${report.written}`);
  return report;
}

if (require.main === module) {
  try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
module.exports = {findMatches, calibrate, rescore, apply, select, POOLS, main};
