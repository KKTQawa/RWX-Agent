'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const {loadConfig, current} = require('../config');
const base = require('../stage1-v2');
const provisional = require('../stage1-v2-provisional');
const {saturationCheck} = require('../tools/stage1_provisional');

function commands(rows) {
  return rows.map(([type, time], line) => ({type, time, line: line + 1}));
}

const SAMPLE = commands([['B', 10], ['A', 15], ['B', 80], ['A', 85], ['B', 150], ['A', 155],
  ['B', 220], ['A', 225], ['B', 290], ['A', 295], ['B', 360], ['A', 365]]);
const NATIVE = [10, 80, 150, 220, 290, 360];

test('stage1 v2-provisional reads its own frozen parameter block', () => {
  const config = loadConfig();
  const block = config.stage1.v2_provisional;
  assert.equal(provisional.VERSION, block.version);
  assert.equal(provisional.VERSION, 'stage1-score-v2-provisional');
  assert.equal(block.status, 'provisional-frozen');
  assert.deepEqual(current('stage1.v2_provisional.parameters.groupWeights'), {startup: 20, cycle: 40, silence: 40});
  assert.equal(current('stage1.v2_provisional.parameters.lambda'), 0);
  assert.equal(current('stage1.v2_provisional.parameters.activityGateEnabled'), false);
  const thresholds = current('stage1.v2_provisional.parameters.featureThresholdsSeconds');
  assert.deepEqual(thresholds.f5, [5, 88.568]);
  assert.deepEqual(thresholds.f6, [3, 107.472]);
  assert.equal(provisional.CALIBRATION.matches, 26);
});

test('stage1 v2-provisional relaxes only f5/f6 hi and disables the activity gate', () => {
  const oldScore = base.scoreEvidence(SAMPLE, NATIVE, 300);
  const newScore = provisional.scoreEvidence(SAMPLE, NATIVE, 300);
  assert.equal(oldScore.features.f5.value, 70);
  assert.equal(oldScore.features.f6.value, 70);
  assert.equal(oldScore.features.f5.u, 1, 'the old f5 hi=60 saturates at 70 s');
  assert.equal(oldScore.features.f6.u, 1, 'the old f6 hi=45 saturates at 70 s');
  assert.ok(newScore.features.f5.u < 1 && newScore.features.f5.u > 0.7);
  assert.ok(newScore.features.f6.u < 1 && newScore.features.f6.u > 0.6);
  assert.ok(newScore.score > oldScore.score, 'relaxing hi must raise the provisional score');
  assert.equal(oldScore.activity.enabled, true);
  assert.equal(newScore.activity.enabled, false);
  assert.equal(newScore.status, 'provisional-frozen');
});

test('stage1 v2-provisional keeps other thresholds and weights frozen', () => {
  const p = provisional.PARAMETERS;
  assert.deepEqual(p.featureThresholdsSeconds.f1, [3, 90]);
  assert.deepEqual(p.featureThresholdsSeconds.f2, [5, 30]);
  assert.deepEqual(p.featureThresholdsSeconds.f3, [5, 35]);
  assert.deepEqual(p.featureThresholdsSeconds.f4, [5, 60]);
  assert.equal(p.minimumNativeCommandsPerMinute, 2);
  assert.equal(p.activityGateScoreCap, 60);
  assert.equal(p.activityGateEnabled, false);
  assert.equal(p.lambda, 0);
});

test('stage1 v2-provisional does not cap a low-activity match', () => {
  const low = provisional.scoreEvidence(commands([['B', 10], ['B', 11]]), [10], 1200);
  assert.equal(low.activity.nativeCommandsPerMinute < 2, true);
  assert.equal(low.activity.applied, false);
  assert.equal(low.activity.enabled, false);
});

test('P90 calibration leaves the worst three matches saturated', () => {
  const values = Array.from({length: 26}, (_, index) => index + 1);
  const hi = base.quantile(values, .9);
  assert.equal(values.filter(value => value >= hi).length, 3);
});

test('saturation check fails only scored features above 40%, never diagnostic f4', () => {
  const row = (id, u1, u2, u4) => ({match: id,
    newU: {f1: u1, f2: u2, f3: 0, f4: u4, f5: 0, f6: 0}});
  const rows = [row('a', 1, 1, 1), row('b', 1, 1, 1), row('c', 0, 1, 1),
    row('d', 0, 0, 1), row('e', 0, 0, 1)];
  const check = saturationCheck(rows, 0.4);
  assert.equal(check.pass, false);
  assert.deepEqual(check.violations, ['f2']);
  assert.equal(check.features.find(feature => feature.id === 'f1').pass, true, '2/5 = 40% passes');
  assert.equal(check.features.find(feature => feature.id === 'f2').pass, false, '3/5 = 60% fails');
  assert.equal(check.features.find(feature => feature.id === 'f4').pass, null, 'f4 is diagnostic only');
  assert.equal(check.features.find(feature => feature.id === 'f4').count, 5);
});
