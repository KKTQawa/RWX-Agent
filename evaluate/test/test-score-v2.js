'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const {loadConfig, current, currentTree, FILE} = require('../config');
const {scoreEvidence, rawFeatures, DEFAULTS: STAGE1} = require('../stage1-v2');
const stage3 = require('../score_stage_3');
const total = require('../score_match_v2');

const META = new Set(['description', 'version', 'status']);
function knobs(node, trail = []) {
  if (node == null || typeof node !== 'object' || Array.isArray(node)) return [];
  if (Object.prototype.hasOwnProperty.call(node, 'current')) return [[trail.join('.'), node]];
  return Object.entries(node).flatMap(([key, value]) =>
    META.has(key) ? [] : knobs(value, [...trail, key]));
}

test('config.json is the single parameter ledger and every knob is described', () => {
  const config = loadConfig();
  assert.equal(config.schema, 1);
  assert.equal(config.version, 'rwx-evaluation-config-v1');
  assert.ok(fs.statSync(FILE).isFile());
  const rows = ['total', 'stage1', 'stage2', 'stage3'].flatMap(section => knobs(config[section], [section]));
  assert.ok(rows.length >= 40, `expected the stage 1-3 knobs, got ${rows.length}`);
  for (const [dotted, node] of rows) {
    assert.ok(node.description, `${dotted}: missing description`);
    assert.ok('initial' in node, `${dotted}: missing initial value`);
    assert.ok('current' in node, `${dotted}: missing current value`);
  }
  const stage3Params = current('stage3.parameters');
  assert.equal(stage3Params.ambush.PMax, 100);
  assert.equal(stage3Params.barrage.PMax, 100);
  assert.equal(stage3Params.grinder.SingleMax, 8);
  assert.equal(stage3Params.grinder.Cap, 100);
  assert.equal(stage3Params.funds.releaseShare, 0.75);
  assert.deepEqual(current('policy.tuningPool').excludeDisposition, ['worthless']);
  assert.deepEqual(Object.keys(currentTree({a: {description: 'x', current: 1}})), ['a']);
  // Module versions must come from the same file, otherwise the ledger and the code drift apart.
  assert.equal(total.VERSION, config.total.v2.version);
  assert.equal(stage3.VERSION, config.stage3.version);
  assert.deepEqual(Object.keys(STAGE1).sort(),
    Object.keys(current('stage1.v2.parameters')).sort(), 'stage1-v2 reads its own parameter block');
});

function commands(rows) {
  return rows.map(([type, time], line) => ({type, time, line: line + 1}));
}

test('stage1-v2 derives features, shrinks few samples and computes the three groups', () => {
  const cmds = commands([['B', 10], ['A', 20], ['B', 60], ['B', 62]]);
  const evidence = rawFeatures(cmds, [10, 40, 100], 600, STAGE1);
  assert.equal(evidence.values.f1, 10);
  assert.equal(evidence.values.f2, 40);
  assert.equal(evidence.values.f3, 10);
  assert.equal(evidence.values.f5, 538, 'the tail window counts as a silence sample');
  assert.equal(evidence.values.f6, 500);

  const score = scoreEvidence(cmds, [10, 40, 100], 600);
  const [lo3, hi3] = STAGE1.featureThresholdsSeconds.f3;
  const raw = (Math.log1p(10) - Math.log1p(lo3)) / (Math.log1p(hi3) - Math.log1p(lo3));
  assert.ok(Math.abs(score.features.f3.u - (raw + 4) / 5) < 1e-3, 'one sample shrinks towards the worst case');
  assert.equal(score.features.f2.u, 1, 'a single very late A block saturates f2');
  assert.equal(score.features.f3.lowConfidence, true);
  assert.equal(score.features.f4.diagnosticOnly, true);
  assert.ok(score.score > 0 && score.score < 100);
  assert.equal(score.eligible, true);
  assert.ok(Math.abs(score.deduction - (100 - score.score)) < 1e-9);
});

test('stage1-v2 bounds: no A block saturates cycle features, short matches are not scored, low activity is capped', () => {
  const noA = scoreEvidence(commands([['B', 10], ['B', 40]]), [10, 40], 600);
  assert.equal(noA.features.f2.u, 1);
  assert.equal(noA.features.f3.u, 1);
  assert.equal(scoreEvidence(commands([['B', 10]]), [10], 299).eligible, false);
  const idle = scoreEvidence(commands([['B', 10], ['B', 11]]), [10], 1200);
  assert.equal(idle.activity.applied, true);
  assert.ok(idle.score <= STAGE1.activityGateScoreCap);
});

test('stage3 funds v2 reads hoarding intervals and honours releaseShare from the ledger', () => {
  // theta = K * income = 30. Funds climb to 1000, drain to 50 and recover to 1100: the drain is one
  // counted spend, and whether it ends the interval depends only on releaseShare. Both ends are low
  // so the scored interval touches neither match start nor match end (those are excluded by design).
  const sample = (funds, second) => ({second, funds, incomePerSecond: 1});
  const decline = [900, 800, 700, 600, 500, 400, 300, 200, 100, 50];
  const low = count => Array.from({length: count}, () => 10);
  const samples = [
    ...low(5), ...Array.from({length: 31}, () => 1000), ...decline,
    ...Array.from({length: 30}, () => 1100), ...low(5),
  ].map(sample);
  const summary = {durationMs: samples.length * 1000, complete: true};
  const params = stage3.DEFAULTS.funds;
  const pin = {windowFraction: 1, medianWindowSeconds: 3, incomeWindowSeconds: 30};
  const base = stage3.scoreEvents([], summary, {funds: pin}, samples);
  const share = base.financialEvents[0].spends[0].share;
  assert.ok(share > 0.8 && share < 1, `the big drain releases ${share} of the peak`);
  const closed = stage3.scoreEvents([], summary,
    {funds: {...params, releaseShare: share - 0.01, ...pin}}, samples);
  const kept = stage3.scoreEvents([], summary,
    {funds: {...params, releaseShare: share + 0.01, ...pin}}, samples);
  const fundsOf = score => score.breakdown.find(row => row.family === 'STAGE3_FUNDS');
  assert.equal(fundsOf(closed).items.length, 2,
    'a release above releaseShare ends the interval and a new one starts');
  assert.equal(fundsOf(kept).items.length, 1,
    'a release below releaseShare keeps the same interval alive');
  const funds = fundsOf(kept);
  assert.equal(funds.cap, params.Cap);
  assert.ok(funds.items[0].durationSeconds > params.d0, 'the interval outlives the grace window');
  assert.ok(funds.items[0].severity > 0 && funds.items[0].severity <= 1);
  assert.ok(Math.abs(funds.items[0].points - params.eventMax * funds.items[0].severity) < 0.01);
});

test('stage3 funds can exempt intervals reaching match start or match end', () => {
  const sample = (funds, second) => ({second, funds, incomePerSecond: 1});
  const high = count => Array.from({length: count}, () => 1000);
  const low = count => Array.from({length: count}, () => 10);
  const fundsOf = score => score.breakdown.find(row => row.family === 'STAGE3_FUNDS');
  // Funds are above theta (30) from the first sample and stay there: one interval spanning the match.
  const whole = [...high(200)].map(sample);
  const wholeScore = fundsOf(stage3.scoreEvents([], {durationMs: 200000, complete: true}, {funds: {windowFraction: 1, excludeEdgeIntervals: true, warmupSeconds: 0}}, whole));
  assert.equal(wholeScore.items.length, 0, 'an interval spanning the whole match is not scored');
  assert.deepEqual(wholeScore.excluded.map(row => row.reason), ['IGNORED_WHOLE_MATCH']);
  assert.equal(wholeScore.deduction, 0);
  assert.equal(wholeScore.diagnostics.ignoredIntervals, 1);
  // Opening only: high from second 0, then a low tail that closes the interval before the end.
  const opening = [...high(200), ...low(5)].map(sample);
  const openingScore = fundsOf(stage3.scoreEvents([], {durationMs: 205000, complete: true}, {funds: {windowFraction: 1, excludeEdgeIntervals: true, warmupSeconds: 0}}, opening));
  assert.equal(openingScore.items.length, 0);
  assert.deepEqual(openingScore.excluded.map(row => row.reason), ['IGNORED_OPENING']);
  // Trailing only: a low opening, then high funds through the last sample.
  const trailing = [...low(5), ...high(200)].map(sample);
  const trailingScore = fundsOf(stage3.scoreEvents([], {durationMs: 205000, complete: true}, {funds: {windowFraction: 1, excludeEdgeIntervals: true, warmupSeconds: 0}}, trailing));
  assert.equal(trailingScore.items.length, 0);
  assert.deepEqual(trailingScore.excluded.map(row => row.reason), ['IGNORED_TRAILING']);
});

test('stage3 flags missing economy evidence instead of scoring zero', () => {
  const score = stage3.scoreEvents([], {durationMs: 600000, complete: true});
  const funds = score.breakdown.find(row => row.family === 'STAGE3_FUNDS');
  assert.equal(funds.deduction, 0);
  assert.equal(score.evidenceComplete, false);
  assert.deepEqual(funds.excluded, [{id: null, reason: 'ECONOMY_EVIDENCE_MISSING'}]);
});

test('tuning pool excludes worthless reviews but keeps scoring them', () => {
  const {collect, calibrate} = require('../tuning_pool');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rwx-pool-'));
  const write = (name, disposition, S) => {
    const dir = path.join(root, name);
    fs.mkdirSync(path.join(dir, 'stage_3'), {recursive: true});
    fs.writeFileSync(path.join(dir, 'meta.json'), JSON.stringify({evaluation: {disposition}}));
    fs.writeFileSync(path.join(dir, 'stage_3', 'score.json'), JSON.stringify({version: 'stage3-score-v2',
      evidenceComplete: true, durationSeconds: 600,
      breakdown: [{family: 'STAGE3_AMBUSH', S, diagnostics: {records: 2}},
        {family: 'STAGE3_BARRAGE', S: S / 2, diagnostics: {records: 1}}]}));
  };
  write('a', null, 10); write('b', 'worthless', 30); write('c', null, 20);
  const config = {policy: {tuningPool: {minDurationExclusiveSeconds: 0, requireCompleteEvidence: true,
    requireFaithfulReplay: true, excludeDisposition: ['worthless']}}};
  const pool = collect(root, config);
  assert.deepEqual(pool.rows.map(row => row.match), ['a', 'c']);
  assert.deepEqual(pool.excluded.map(row => [row.match, row.reasons]), [['b', ['disposition:worthless']]]);
  const calibration = calibrate(pool, {minimum: 2});
  assert.equal(calibration.ambushS0, 15);
  assert.equal(calibration.barrageS0, 7.5);
  fs.rmSync(root, {recursive: true, force: true});
});

test('funds calibration follows the design quantile rules and keeps priors below 30 intervals', () => {
  const {quantile, fundsCalibration} = require('../tuning_pool');
  assert.equal(quantile([1, 2, 3, 4], 0.5), 2.5);
  assert.ok(Math.abs(quantile([1, 2, 3, 4], 0.9) - 3.7) < 1e-9);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rwx-funds-'));
  const writeEconomy = (name, samples) => {
    const dir = path.join(root, name, 'prepared');
    fs.mkdirSync(dir, {recursive: true});
    const lines = [];
    for (let index = 0; index < samples.length; index += 60)
      lines.push(samples.slice(index, index + 60).map(row => `${row.funds}(+${row.income})`).join(','));
    fs.writeFileSync(path.join(dir, 'economy.log'), lines.join('\n') + '\n');
  };
  const low = second => ({second, funds: 10, income: 64});
  const prior = {K: 30, d0: 15, d1: 120, incomeWindowSeconds: 30, medianWindowSeconds: 3,
    incomeFieldPerSecond: 1.5625, spendFloor: 800, spendShare: 0.25, rho1: 0.5, rho2: 0.25, releaseShare: 0.8};
  // One match with 31 hoarding blocks: ratio funds/income = 100, so K clips to 45.
  const samples = [];
  for (let index = 0; index < 5; index++) samples.push(low(samples.length));
  for (let block = 0; block < 31; block++) {
    for (let index = 0; index < 40; index++) samples.push({second: samples.length, funds: 10000, income: 64});
    for (let index = 0; index < 5; index++) samples.push(low(samples.length));
  }
  writeEconomy('tall', samples);
  const result = fundsCalibration(root, [{match: 'tall', relativePath: 'tall'}], prior, {minimumIntervals: 30});
  assert.equal(result.calibrated, true);
  assert.equal(result.params.K, 45, 'median Q0.9 above the clip keeps K at 45');
  assert.equal(result.stats.intervals, 31, 'edge intervals are not reference intervals');
  assert.ok(result.params.d0 >= 8 && result.params.d0 <= 25);
  assert.ok(result.params.d1 >= 90 && result.params.d1 <= 180);
  // Fewer than 30 reference intervals keeps the priors, as the design requires.
  const thin = [...Array.from({length: 5}, low), ...Array.from({length: 40}, () => ({funds: 10000, income: 64})),
    ...Array.from({length: 5}, low)].map((row, second) => ({...row, second}));
  writeEconomy('thin', thin);
  const fallback = fundsCalibration(root, [{match: 'thin', relativePath: 'thin'}], prior, {minimumIntervals: 30});
  assert.equal(fallback.calibrated, false);
  assert.match(fallback.reason, /intervals_below_30/);
  assert.deepEqual(fallback.params, {K: prior.K, d0: prior.d0, d1: prior.d1});
  fs.rmSync(root, {recursive: true, force: true});
});

test('total-v2 subtracts the Stage3 shortfall from Stage1-v2 and rejects stale reports', () => {
  // score_design v2: S = stage1v2 − (100 − stage3) × (1 − k)
  assert.equal(total.combined(50, 80, 0.6), 42);
  assert.equal(total.combined(80, 100, 0.5), 80, 'a perfect Stage3 keeps the Stage1-v2 score');
  assert.equal(total.combined(10, 0, 0.5), 0, 'the result is clamped at zero');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rwx-v2-total-'));
  const dir = path.join(root, 'match');
  fs.mkdirSync(path.join(dir, 'stage_1_v2'), {recursive: true});
  fs.mkdirSync(path.join(dir, 'stage_3'), {recursive: true});
  fs.writeFileSync(path.join(dir, 'stage_1_v2', 'score.json'), JSON.stringify({version: 'stage1-score-v2',
    eligible: true, score: 50, provisionalReasons: ['uncalibrated thresholds']}));
  fs.writeFileSync(path.join(dir, 'stage_3', 'score.json'), JSON.stringify({version: 'stage3-score-v2',
    evidenceComplete: true, total: 80, calibration: {reasons: ['S0 provisional']}}));
  const score = total.main(['node', 'score_match_v2.js', dir]);
  assert.equal(score.total, 40, 'k=0.5 halves the 20 point Stage3 shortfall');
  assert.equal(score.components.stage3.weight, 0.5);
  assert.deepEqual(score.provisionalReasons, ['uncalibrated thresholds', 'S0 provisional']);
  assert.ok(fs.existsSync(path.join(dir, 'score_v2.json')));
  fs.writeFileSync(path.join(dir, 'stage_3', 'score.json'), JSON.stringify({version: 'stage3-score-v1',
    evidenceComplete: true, total: 80}));
  assert.throws(() => total.main(['node', 'score_match_v2.js', dir]), /version/);
  fs.rmSync(root, {recursive: true, force: true});
});

test('stage3 funds scores edge intervals once the exemption is off', () => {
  const sample = (funds, second) => ({second, funds, incomePerSecond: 1});
  const high = count => Array.from({length: count}, () => 1000);
  const low = count => Array.from({length: count}, () => 10);
  const fundsOf = score => score.breakdown.find(row => row.family === 'STAGE3_FUNDS');
  const open = {funds: {windowFraction: 1, excludeEdgeIntervals: false, warmupSeconds: 0, d1: 180}};
  // Whole match above theta: previously IGNORED_WHOLE_MATCH (0 points), now a ~199 s interval.
  const whole = [...high(200)].map(sample);
  const wholeScore = fundsOf(stage3.scoreEvents([], {durationMs: 200000, complete: true}, open, whole));
  assert.equal(wholeScore.items.length, 1);
  assert.equal(wholeScore.items[0].severity, 1, '199 s is far past d1');
  assert.equal(wholeScore.items[0].points, stage3.DEFAULTS.funds.eventMax);
  assert.equal(wholeScore.diagnostics.excludeEdgeIntervals, false);
  assert.equal(wholeScore.diagnostics.edgeScored, 1);
  assert.equal(wholeScore.excluded.length, 0);
  // Opening-only and trailing-only behave the same way.
  const opening = [...high(200), ...low(5)].map(sample);
  assert.equal(fundsOf(stage3.scoreEvents([], {durationMs: 205000, complete: true}, open, opening)).items.length, 1);
  const trailing = [...low(5), ...high(200)].map(sample);
  assert.equal(fundsOf(stage3.scoreEvents([], {durationMs: 205000, complete: true}, open, trailing)).items.length, 1);
});
