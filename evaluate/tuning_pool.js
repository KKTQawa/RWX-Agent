'use strict';
/**
 * The tuning pool is the only source of the corpus-level Stage-3 constants (`S0`). It is defined by
 * `config.json.policy.tuningPool`, not by which matches happened to be re-evaluated in one command:
 *
 *   - every match directly under `evaluate/output/` (archives never enter),
 *   - score window strictly greater than `minDurationExclusiveSeconds`,
 *   - Stage-3 evidence complete, replay faithful (live evidence has no `playback.json`),
 *   - `meta.json.evaluation.disposition` not in `excludeDisposition` (`worthless` is a review
 *     label: it still gets scored and published, it only stops moving the global constants),
 *   - optional `requireOutcome`.
 *
 * Rows carry the pre-saturation `S` of the two saturated families. `S` does not depend on `S0`
 * (only the final deduction does), so the median can be recomputed at any time from the reports.
 */
const fs = require('node:fs');
const path = require('node:path');
const {economySeconds} = require('./score_stage_2');
const {fundsEvents} = require('./events/score');

const readJson = file => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));

function matchDirectories(root) {
  if (!fs.existsSync(root)) return [];
  return fs.readdirSync(root, {withFileTypes: true})
    .filter(entry => entry.isDirectory() && !['_archive', 'micro', 'events-live'].includes(entry.name))
    .map(entry => path.join(root, entry.name))
    .filter(dir => fs.existsSync(path.join(dir, 'stage_3', 'score.json')))
    .sort();
}

function replayState(dir) {
  const file = path.join(dir, 'resim', 'playback.json');
  if (!fs.existsSync(file)) return {faithful: true, checksumWarnings: null, source: 'live'};
  const playback = readJson(file), checksumWarnings = Number(playback.checksumWarnings ?? 0);
  return {faithful: checksumWarnings === 0, checksumWarnings, source: playback.source || 'resim'};
}

function outcomeOf(dir, meta) {
  const evaluation = path.join(dir, 'evaluation_v2.json');
  if (fs.existsSync(evaluation)) {
    const result = readJson(evaluation).result;
    if (result && result.outcome) return result.outcome;
  }
  return meta?.result?.outcome || 'unknown';
}

function collect(root, config) {
  const policy = config.policy?.tuningPool || {};
  const excludedDispositions = policy.excludeDisposition || [];
  const minDuration = Number(policy.minDurationExclusiveSeconds ?? 0);
  const rows = [], excluded = [];
  for (const dir of matchDirectories(root)) {
    const match = path.basename(dir);
    const metaFile = path.join(dir, 'meta.json');
    const meta = fs.existsSync(metaFile) ? readJson(metaFile) : null;
    const stage3 = readJson(path.join(dir, 'stage_3', 'score.json'));
    const disposition = meta?.evaluation?.disposition || null;
    const outcome = outcomeOf(dir, meta);
    const replay = replayState(dir);
    const family = name => (stage3.breakdown || []).find(row => row.family === name);
    const ambush = family('STAGE3_AMBUSH'), barrage = family('STAGE3_BARRAGE');
    const row = {match, relativePath: path.relative(root, dir).replace(/\\/g, '/'),
      durationSeconds: stage3.durationSeconds, outcome, disposition, replay: replay.source,
      ambushS: ambush?.S ?? null, barrageS: barrage?.S ?? null,
      records: {ambush: ambush?.diagnostics?.records ?? 0, barrage: barrage?.diagnostics?.records ?? 0}};
    const reasons = [];
    if (!(Number(row.durationSeconds) > minDuration)) reasons.push('window');
    if (policy.requireCompleteEvidence !== false && stage3.evidenceComplete !== true) reasons.push('evidence_incomplete');
    if (policy.requireFaithfulReplay !== false && !replay.faithful)
      reasons.push(`replay_desync:${replay.checksumWarnings}`);
    if (disposition && excludedDispositions.includes(disposition)) reasons.push(`disposition:${disposition}`);
    if (policy.requireOutcome && outcome !== policy.requireOutcome) reasons.push(`outcome:${outcome}`);
    if (reasons.length) excluded.push({...row, reasons});
    else rows.push(row);
  }
  return {rows, excluded, policy};
}

function quantile(values, q) {
  const numbers = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!numbers.length) return null;
  const position = (numbers.length - 1) * q, low = Math.floor(position), high = Math.ceil(position);
  return low === high ? numbers[low] : numbers[low] + (numbers[high] - numbers[low]) * (position - low);
}

function median(values) { return quantile(values, 0.5); }

/** Centred median smoothing, same convention as `fundsEvents` (endpoints use what is available). */
function smoothedFunds(samples, windowSeconds = 3) {
  const half = Math.max(0, Math.floor((Number(windowSeconds) - 1) / 2));
  return samples.map((row, index) => {
    const values = samples.slice(Math.max(0, index - half), index + half + 1)
      .map(item => item.funds).sort((a, b) => a - b);
    const n = values.length;
    return (values[(n - 1) >> 1] + values[n >> 1]) / 2;
  });
}

/** Trailing mean of the per-second income rate, the denominator of `K`. */
function trailingIncomeRate(samples, incomeFieldPerSecond, windowSeconds = 30) {
  const window = Math.max(1, Number(windowSeconds));
  const rates = [], values = samples.map(row => row.incomeField * incomeFieldPerSecond);
  let sum = 0;
  for (let index = 0; index < values.length; index++) {
    sum += values[index];
    if (index >= window) sum -= values[index - window];
    rates.push(sum / Math.min(window, index + 1));
  }
  return rates;
}

function economyFile(root, relativePath) {
  const dir = path.join(root, relativePath);
  return [path.join(dir, 'prepared', 'economy.log'), path.join(dir, 'resim', 'economy.log'),
    path.join(dir, 'stage_3', 'economy.log')].find(file => fs.existsSync(file)) || null;
}

/**
 * Design `§资金空余v2·参数校准`: the hoarding threshold and the two time knots are estimated from the
 * reference pool (this batch), then clipped:
 *
 *   K  = clip(median_m Q0.9(r_m), 20, 45),  r_m(t) = smoothed funds / trailing-30s income rate
 *   d0 = clip(Q0.5(d_k), 8, 25),  d1 = clip(Q0.95(d_k), 90, 180)   (intervals recomputed with that K)
 *
 * With fewer than 30 reference intervals the design keeps the priors. Edge intervals (match
 * start/end) are excluded, exactly like scoring.
 */
function fundsCalibration(root, rows, fundsParams, options = {}) {
  const minimumIntervals = Number(options.minimumIntervals ?? 30);
  const incomeFieldPerSecond = Number(fundsParams.incomeFieldPerSecond ?? 1.5625);
  const medianWindow = Number(fundsParams.medianWindowSeconds ?? 3);
  const incomeWindow = Number(fundsParams.incomeWindowSeconds ?? 30);
  const prior = {K: fundsParams.K, d0: fundsParams.d0, d1: fundsParams.d1};
  const matches = [];
  for (const row of rows) {
    const file = economyFile(root, row.relativePath);
    if (!file) continue;
    const samples = economySeconds(file);
    const smoothed = smoothedFunds(samples, medianWindow);
    const rates = trailingIncomeRate(samples, incomeFieldPerSecond, incomeWindow);
    const ratios = smoothed.map((funds, index) => (rates[index] > 0 ? funds / rates[index] : null))
      .filter(Number.isFinite);
    matches.push({match: row.match, samples, q90: quantile(ratios, 0.9)});
  }
  const medians = matches.map(item => item.q90).filter(Number.isFinite);
  if (!medians.length) return {calibrated: false, reason: 'no_economy', params: prior, stats: {matches: 0, intervals: 0}};
  const medianQ90 = median(medians);
  const K = Math.max(20, Math.min(45, medianQ90));
  const durations = [];
  for (const item of matches)
    for (const event of fundsEvents(item.samples, {...fundsParams, K}))
      if (!event.edge) durations.push(event.durationSeconds);
  if (durations.length < minimumIntervals)
    return {calibrated: false, reason: `intervals_below_${minimumIntervals}`, params: prior,
      stats: {matches: matches.length, intervals: durations.length, medianQ90: round(medianQ90)}};
  const q50 = quantile(durations, 0.5), q95 = quantile(durations, 0.95);
  const d0 = Math.max(8, Math.min(25, q50)), d1 = Math.max(90, Math.min(180, q95));
  return {calibrated: true,
    params: {K: round(K), d0: round(d0), d1: round(d1)},
    stats: {matches: matches.length, intervals: durations.length,
      medianQ90: round(medianQ90), q50: round(q50), q95: round(q95), clips: {K: [20, 45], d0: [8, 25], d1: [90, 180]}}};
}

const round = (value, digits = 3) => Number(Number(value).toFixed(digits));

function calibrate(pool, options = {}) {
  const minimum = Number(options.minimum ?? 3);
  const ambushMedian = median(pool.rows.map(row => row.ambushS));
  const barrageMedian = median(pool.rows.map(row => row.barrageS));
  return {matches: pool.rows.length, minimum, enough: pool.rows.length >= minimum,
    ambushS0: ambushMedian, barrageS0: barrageMedian};
}

module.exports = {matchDirectories, replayState, collect, median, quantile, calibrate,
  smoothedFunds, trailingIncomeRate, fundsCalibration};
