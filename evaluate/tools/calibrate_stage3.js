#!/usr/bin/env node
'use strict';
/**
 * Recalibrate the corpus-level Stage-3 constants (`S0` of the two saturated families) from the
 * tuning pool and, with `--write`, persist them into `evaluate/config.json`.
 *
 * This is the "global parameter optimisation" step: after a match is (re-)scored, the pool is
 * every current match that qualifies under `policy.tuningPool` — `worthless` matches are excluded
 * from the pool but still keep their own scores. `S` does not depend on `S0`, so the medians can be
 * recomputed without re-running any stage.
 *
 * Usage:
 *   node evaluate/tools/calibrate_stage3.js [--root evaluate/output] [--min 3] [--write]
 *        [--out <step.json>] [--label <text>]
 */
const fs = require('node:fs');
const path = require('node:path');
const {FILE, loadConfig, current} = require('../config');
const {collect, calibrate, fundsCalibration} = require('../tuning_pool');

const ROOT = path.resolve(__dirname, '..', '..');
const OUTPUT = path.join(ROOT, 'evaluate', 'output');
const round = (value, digits = 3) => Number(Number(value).toFixed(digits));

function localTimestamp(date = new Date()) {
  const pad = (value, width = 2) => String(value).padStart(width, '0');
  const offset = -date.getTimezoneOffset(), sign = offset >= 0 ? '+' : '-', absolute = Math.abs(offset);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:` +
    `${pad(date.getMinutes())}:${pad(date.getSeconds())}${sign}${pad(Math.floor(absolute / 60))}:${pad(absolute % 60)}`;
}

function counts(rows) {
  const outcomes = {};
  for (const row of rows) outcomes[row.outcome] = (outcomes[row.outcome] || 0) + 1;
  return outcomes;
}

function step(root, options = {}) {
  const config = loadConfig();
  const pool = collect(root || OUTPUT, config);
  const result = calibrate(pool, {minimum: options.minimum ?? 3});
  const funds = fundsCalibration(root || OUTPUT, pool.rows, current('stage3.parameters.funds', config),
    {minimumIntervals: options.minimumIntervals ?? 30});
  const previous = {ambushS0: current('stage3.parameters.ambush.S0', config),
    barrageS0: current('stage3.parameters.barrage.S0', config),
    K: current('stage3.parameters.funds.K', config), d0: current('stage3.parameters.funds.d0', config),
    d1: current('stage3.parameters.funds.d1', config)};
  const enough = result.enough && Number.isFinite(result.ambushS0) && Number.isFinite(result.barrageS0);
  const next = {
    ...(enough ? {ambushS0: round(result.ambushS0), barrageS0: round(result.barrageS0)}
      : {ambushS0: previous.ambushS0, barrageS0: previous.barrageS0}),
    ...(funds.calibrated ? {K: funds.params.K, d0: funds.params.d0, d1: funds.params.d1}
      : {K: previous.K, d0: previous.d0, d1: previous.d1}),
  };
  const changed = Object.keys(next).some(key => next[key] !== previous[key]);
  return {schema: 1, timestamp: localTimestamp(), label: options.label || null,
    pool: {matches: pool.rows.length, excluded: pool.excluded.length,
      worthless: pool.excluded.filter(row => row.reasons.includes('disposition:worthless')).length,
      minimum: result.minimum, calibrate: enough},
    outcomes: counts(pool.rows), excluded: pool.excluded,
    previous, next, changed, funds,
    medians: {ambush: result.ambushS0, barrage: result.barrageS0}, matches: pool.rows};
}

function persist(record, configFile = FILE) {
  const config = JSON.parse(fs.readFileSync(configFile, 'utf8').replace(/^\uFEFF/, ''));
  config.updatedAt = record.timestamp;
  config.stage3.parameters.ambush.S0.current = record.next.ambushS0;
  config.stage3.parameters.barrage.S0.current = record.next.barrageS0;
  config.stage3.parameters.funds.K.current = record.next.K;
  config.stage3.parameters.funds.d0.current = record.next.d0;
  config.stage3.parameters.funds.d1.current = record.next.d1;
  config.stage3.calibration.current = {
    source: 'current-all-complete-matches',
    matches: record.pool.matches,
    outcomes: record.outcomes,
    minDurationExclusiveSeconds: 0,
    excludedDisposition: config.policy?.tuningPool?.excludeDisposition || [],
    funds: record.funds.calibrated
      ? {source: 'reference-pool-quantiles', ...record.funds.params, ...record.funds.stats}
      : {source: 'prior', reason: record.funds.reason, ...record.funds.stats},
  };
  fs.writeFileSync(configFile, JSON.stringify(config, null, 2) + '\n', 'utf8');
  return config;
}

function main(argv = process.argv) {
  const args = argv.slice(2), options = {};
  while (args.length) {
    const flag = args.shift();
    if (flag === '--write') options.write = true;
    else if (flag === '--min') options.minimum = Number(args.shift());
    else if (flag === '--intervals') options.minimumIntervals = Number(args.shift());
    else if (flag === '--root') options.root = path.resolve(args.shift());
    else if (flag === '--out') options.out = path.resolve(args.shift());
    else if (flag === '--label') options.label = args.shift();
    else throw Error('Usage: node evaluate/tools/calibrate_stage3.js [--root <dir>] [--min 3] [--intervals 30] [--write] [--out <file>] [--label <text>]');
  }
  const record = step(options.root, options);
  if (options.write) record.written = persist(record).updatedAt;
  if (options.out) {
    fs.mkdirSync(path.dirname(options.out), {recursive: true});
    fs.writeFileSync(options.out, JSON.stringify(record, null, 2) + '\n', 'utf8');
  }
  const poolText = `${record.pool.matches} 局入池 / ${record.pool.excluded} 局排除（worthless ${record.pool.worthless}）`;
  console.log(`S0 ${record.previous.ambushS0} / ${record.previous.barrageS0} -> ` +
    `${record.next.ambushS0} / ${record.next.barrageS0}${record.pool.calibrate ? '' : '（样本不足，保持）'}；` +
    `funds K/d0/d1 ${record.previous.K}/${record.previous.d0}/${record.previous.d1} -> ` +
    `${record.next.K}/${record.next.d0}/${record.next.d1}` +
    `${record.funds.calibrated ? `（${record.funds.stats.intervals} 区间）` : `（${record.funds.reason}，保持）`}；${poolText}`);
  return record;
}

if (require.main === module) {
  try { main(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
module.exports = {step, persist, localTimestamp};
