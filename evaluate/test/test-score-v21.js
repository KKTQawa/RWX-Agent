'use strict';
const test = require('node:test'), assert = require('node:assert/strict');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const {loadConfig, current} = require('../config');
const funds = require('../funds_v3');
const v21 = require('../score_match_v21');
const stage3v21 = require('../score_stage_3_v21');
const stage3 = require('../score_stage_3');
const v2 = require('../score_match_v2');

/** Piecewise-linear balance through `points`; every sample carries the same income rate. */
function seriesAt(count, points, rate = 1) {
  return Array.from({length: count}, (_, second) => {
    for (let index = 1; index < points.length; index++) {
      const from = points[index - 1], to = points[index];
      if (second <= to.second) {
        const t = to.second === from.second ? 0 : (second - from.second) / (to.second - from.second);
        return {second, funds: from.funds + (to.funds - from.funds) * t, incomePerSecond: rate};
      }
    }
    return {second, funds: points[points.length - 1].funds, incomePerSecond: rate};
  });
}

test('funds v3 splits the window, weights the three Ki and takes the square root', () => {
  const samples = seriesAt(101, [{second: 0, funds: 4000}, {second: 25, funds: 0},
    {second: 75, funds: 5000}, {second: 100, funds: 0}], 100);
  const result = funds.fundsV3(samples);
  assert.equal(result.available, true);
  assert.equal(result.windowSeconds, 100);
  assert.deepEqual(result.windows.map(window => window.k), [1, 0, 1]);
  assert.deepEqual(result.windows.map(window => window.seconds), [25, 50, 25]);
  assert.deepEqual(result.windows.map(window => window.available), [6500, 5000, 7500]);
  assert.equal(result.k, 0.6);
  assert.equal(result.deduction, 18.974);
  assert.equal(result.totalIncome, 10000);
  assert.equal(result.totalAvailable, 14000);
  assert.equal(result.totalSpent, 14000);
  assert.equal(result.globalRawRatio, 1);
});

test('funds v3 spends the balance identity and keeps every window Ki inside [0,1]', () => {
  const idle = funds.fundsV3(seriesAt(101, [{second: 0, funds: 4000}, {second: 100, funds: 14000}], 100));
  assert.equal(idle.k, 0);
  assert.equal(idle.deduction, 30);
  const half = funds.fundsV3(seriesAt(101, [{second: 0, funds: 4000}, {second: 25, funds: 3250},
    {second: 75, funds: 4125}, {second: 100, funds: 3312.5}], 100));
  assert.deepEqual(half.windows.map(window => window.k), [0.5, 0.5, 0.5]);
  assert.equal(half.globalRawRatio, 0.7634);
  assert.equal(half.deduction, 21.213);
  const carryOver = funds.fundsV3(seriesAt(101, [{second: 0, funds: 4000}, {second: 25, funds: 4000},
    {second: 75, funds: 1000}, {second: 100, funds: 1000}], 100));
  assert.equal(carryOver.windows[1].available, 9000);
  assert.equal(carryOver.windows[1].k, 0.8889);
  assert.equal(carryOver.deduction, 18.907);
  assert.equal(funds.fundsV3([{second: 0, funds: 1, incomePerSecond: 1}]).available, false);
});

test('funds v3 counts every window opening balance as income and converts the income field', () => {
  const samples = Array.from({length: 61}, (_, second) => ({second, funds: 4000, incomeField: 64}));
  const result = funds.fundsV3(samples, {incomeFieldPerSecond: 1.5625, singleMax: 30});
  assert.equal(result.totalIncome, 6000);
  assert.equal(result.totalAvailable, 10000);
  assert.deepEqual(result.windows.map(window => window.available), [5500, 7000, 5500]);
  assert.equal(result.globalRawRatio, 0.6);
});

function writeTelemetry(dir, rows) {
  fs.writeFileSync(path.join(dir, 'telemetry.jsonl'), rows.map(row => JSON.stringify(row)).join('\n') + '\n');
}

test('ambush v3: land-only, building attackers filtered, fast events stay in M1, died uses delta', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rwx-v3-ambush-'));
  const rows = [
    {kind: 'damage', timeMs: 1000, hpLoss: 100, shieldLoss: 50,
      victim: {id: 1, type: 'c_tank', side: 'self', building: false},
      attacker: {type: 'c_tank', side: 'enemy', building: false}},
    {kind: 'damage', timeMs: 2000, hpLoss: 50, shieldLoss: 0,
      victim: {id: 1, type: 'c_tank', side: 'self', building: false},
      attacker: {type: 'c_tank', side: 'enemy', building: false}},
    {kind: 'damage', timeMs: 5000, hpLoss: 400, shieldLoss: 0,
      victim: {id: 1, type: 'c_tank', side: 'self', building: false},
      attacker: {type: 'c_turret_t1', side: 'enemy', building: true}},
    {kind: 'damage', timeMs: 1000, hpLoss: 200, shieldLoss: 0,
      victim: {id: 2, type: 'c_interceptor', side: 'self', building: false},
      attacker: {type: 'c_tank', side: 'enemy', building: false}},
    {kind: 'damage', timeMs: 1000, hpLoss: 10, shieldLoss: 0,
      victim: {id: 1, type: 'c_tank', side: 'self', building: false},
      attacker: {type: 'c_tank', side: 'enemy', building: false}},
    {kind: 'damage', timeMs: 10, hpLoss: 10, shieldLoss: 0,
      victim: {id: 1, type: 'c_tank', side: 'self', building: false},
      attacker: {type: 'c_tank', side: 'enemy', building: false}},
    {kind: 'stage3_ambush', phase: 'hit', eventId: 'A1', unitId: 1, timeMs: 1000,
      type: 'c_tank', deltaHp: 100, deltaShield: 50, maxHp: 1000, maxShield: 100, cost: 1000},
    {kind: 'stage3_ambush', phase: 'hit', eventId: 'A1', unitId: 1, timeMs: 2000,
      type: 'c_tank', deltaHp: 50, deltaShield: 0, maxHp: 1000, maxShield: 100, cost: 1000},
    {kind: 'stage3_ambush', phase: 'hit', eventId: 'A1', unitId: 1, timeMs: 5000,
      type: 'c_tank', deltaHp: 400, deltaShield: 0, maxHp: 1000, maxShield: 100, cost: 1000},
    {kind: 'stage3_ambush', phase: 'close', eventId: 'A1', unitId: 1, toMs: 6000, died: false,
      complete: true, maxHp: 1000, maxShield: 100, cost: 1000, type: 'c_tank'},
    {kind: 'stage3_ambush', phase: 'hit', eventId: 'A2', unitId: 2, timeMs: 1000,
      type: 'c_interceptor', deltaHp: 200, deltaShield: 0, maxHp: 500, maxShield: 0, cost: 500},
    {kind: 'stage3_ambush', phase: 'close', eventId: 'A2', unitId: 2, toMs: 1000, died: false,
      complete: true, maxHp: 500, maxShield: 0, cost: 500, type: 'c_interceptor'},
    {kind: 'stage3_ambush', phase: 'hit', eventId: 'A3', unitId: 1, timeMs: 1000,
      type: 'c_tank', deltaHp: 10, deltaShield: 0, maxHp: 1000, maxShield: 0, cost: 1000},
    {kind: 'stage3_ambush', phase: 'close', eventId: 'A3', unitId: 1, toMs: 2000, died: false,
      complete: true, maxHp: 1000, maxShield: 0, cost: 1000, type: 'c_tank'},
    {kind: 'stage3_ambush', phase: 'hit', eventId: 'A4', unitId: 1, timeMs: 10,
      type: 'c_tank', deltaHp: 10, deltaShield: 0, maxHp: 1000, maxShield: 0, cost: 1000},
    {kind: 'stage3_ambush', phase: 'close', eventId: 'A4', unitId: 1, toMs: 10, died: true,
      complete: true, maxHp: 1000, maxShield: 0, cost: 1000, type: 'c_tank'}];
  writeTelemetry(dir, rows);
  const scanned = await stage3v21.readTelemetryV3(path.join(dir, 'telemetry.jsonl'));
  assert.equal(scanned.X1, 190, 'the enemy-unit hits to land victims enter X1');
  assert.equal(scanned.ambush.length, 3, 'the air victim is excluded entirely');
  const a1 = scanned.ambush.find(record => record.id === 'A1');
  assert.equal(a1.N, 2, 'the enemy-building hit is filtered out');
  assert.equal(a1.D_hp, 150);
  assert.equal(a1.D_sh, 50);
  assert.equal(a1.T, 5);

  const score = stage3v21.scoreAmbushV3(scanned.ambush, stage3v21.parameters().ambushV3);
  assert.equal(score.events, 3);
  assert.equal(score.admitted, 2, 'A1 and the one-shot death A4 are admitted; A3 is below epsilon');
  assert.equal(score.fast, 1);
  assert.equal(score.died, 1);
  assert.equal(score.M, 2, 'A4 still contributes one weight to M1');
  assert.ok(score.R > 0.05 && score.R < 0.06);
  assert.ok(score.deduction > 9 && score.deduction < 10);
  fs.rmSync(dir, {recursive: true, force: true});
});

test('barrage v3: T stops at the last shell, single-hit destruction is admitted, short bursts stay in M2', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rwx-v3-barrage-'));
  const rows = [
    {kind: 'stage3_barrage', phase: 'hit', eventId: 'H1', timeMs: 1000, type: 'c_turret_t1',
      deltaHp: 100, deltaShield: 0, maxHp: 1000, maxShield: 0, cost: 500},
    {kind: 'stage3_barrage', phase: 'hit', eventId: 'H1', timeMs: 5000, type: 'c_turret_t1',
      deltaHp: 100, deltaShield: 0, maxHp: 1000, maxShield: 0, cost: 500},
    {kind: 'stage3_barrage', phase: 'hit', eventId: 'H1', timeMs: 9000, type: 'c_turret_t1',
      deltaHp: 100, deltaShield: 0, maxHp: 1000, maxShield: 0, cost: 500},
    {kind: 'stage3_barrage', phase: 'close', eventId: 'H1', toMs: 15000, destroyed: false,
      complete: true, N: 3, maxHp: 1000, maxShield: 0, cost: 500, type: 'c_turret_t1'},
    {kind: 'stage3_barrage', phase: 'hit', eventId: 'H2', timeMs: 1000, type: 'c_turret_t1',
      deltaHp: 1000, deltaShield: 0, maxHp: 1000, maxShield: 0, cost: 500},
    {kind: 'stage3_barrage', phase: 'close', eventId: 'H2', toMs: 1000, destroyed: true,
      complete: true, N: 1, maxHp: 1000, maxShield: 0, cost: 500, type: 'c_turret_t1'},
    {kind: 'stage3_barrage', phase: 'hit', eventId: 'H3', timeMs: 1000, type: 'c_turret_t1',
      deltaHp: 0, deltaShield: 0, maxHp: 1000, maxShield: 0, cost: 500},
    {kind: 'stage3_barrage', phase: 'hit', eventId: 'H3', timeMs: 5000, type: 'c_turret_t1',
      deltaHp: 0, deltaShield: 0, maxHp: 1000, maxShield: 0, cost: 500},
    {kind: 'stage3_barrage', phase: 'close', eventId: 'H3', toMs: 9000, destroyed: false,
      complete: true, N: 2, maxHp: 1000, maxShield: 0, cost: 500, type: 'c_turret_t1'}];
  writeTelemetry(dir, rows);
  const scanned = await stage3v21.readTelemetryV3(path.join(dir, 'telemetry.jsonl'));
  const h1 = scanned.barrage.find(record => record.id === 'H1');
  assert.equal(h1.T, 8, 'T_j ends at the last hit (9000), not the buffer expiry (15000)');
  assert.equal(h1.N, 3);
  const score = stage3v21.scoreBarrageV3(scanned.barrage, stage3v21.parameters().barrageV3);
  assert.equal(score.events, 3);
  assert.equal(score.admitted, 2, 'H3 has zero damage and stays out; H1/H2 are admitted');
  assert.equal(score.destroyed, 1);
  assert.equal(score.M, 1.414, 'H1 and H2 each contribute sqrt(0.5)');
  assert.ok(score.R > 0.04 && score.R < 0.05);
  assert.ok(score.deduction > 6 && score.deduction < 7);
  fs.rmSync(dir, {recursive: true, force: true});
});

function writeMatch(root) {
  const dir = path.join(root, 'match');
  fs.mkdirSync(path.join(dir, 'stage_1_v2'), {recursive: true});
  fs.mkdirSync(path.join(dir, 'stage_3'), {recursive: true});
  fs.mkdirSync(path.join(dir, 'prepared'), {recursive: true});
  fs.writeFileSync(path.join(dir, 'stage_1_v2', 'score.json'), JSON.stringify({version: 'stage1-score-v2',
    eligible: true, score: 60, provisionalReasons: ['prior']}));
  fs.writeFileSync(path.join(dir, 'stage_3', 'score.json'), JSON.stringify({version: 'stage3-score-v2',
    evidenceComplete: true, durationSeconds: 99, total: 40, calibration: {reasons: ['S0']},
    breakdown: [{family: 'STAGE3_AMBUSH', deduction: 60, cap: 100, raw: 1},
      {family: 'STAGE3_BARRAGE', deduction: 0, cap: 100, raw: 0},
      {family: 'STAGE3_GRINDER', deduction: 0, cap: 100, raw: 0},
      {family: 'STAGE3_FUNDS', deduction: 0, cap: 30, raw: 0}]}));
  fs.writeFileSync(path.join(dir, 'stage_3', 'events.jsonl'), '');
  fs.writeFileSync(path.join(dir, 'prepared', 'telemetry.jsonl'), '');
  const points = [{second: 0, funds: 4000}, {second: 24, funds: 3200},
    {second: 74, funds: 4100}, {second: 99, funds: 3300}];
  const rows = [];
  for (let second = 0; second < 100; second++) {
    let funds = points[points.length - 1].funds;
    for (let index = 1; index < points.length; index++) {
      const from = points[index - 1], to = points[index];
      if (second <= to.second) {
        const t = (second - from.second) / (to.second - from.second);
        funds = from.funds + (to.funds - from.funds) * t;
        break;
      }
    }
    rows.push({funds, income: 64});
  }
  const lines = [];
  for (let index = 0; index < rows.length; index += 60)
    lines.push(rows.slice(index, index + 60).map(row => `${row.funds}(+${row.income})`).join(','));
  fs.writeFileSync(path.join(dir, 'prepared', 'economy.log'), lines.join('\n') + '\n');
  return dir;
}

test('score_match_v21 writes stage3-v2.1-v3 and never touches score_v2.json', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rwx-v21-'));
  const dir = writeMatch(root);
  fs.writeFileSync(path.join(dir, 'score_v2.json'), JSON.stringify({version: 'total-v2', total: 30}));
  const score = await v21.main(['node', 'score_match_v21.js', dir, '--quiet']);
  assert.equal(score.fundsV3.k, 0.5);
  assert.equal(score.fundsV3.deduction, 21.213);
  assert.equal(score.components.stage3.ambush.deduction, 0);
  assert.equal(score.components.stage3.barrage.deduction, 0);
  assert.equal(score.components.stage3.grinder.deduction, 0);
  assert.equal(score.components.stage3.value, 78.787);
  assert.equal(score.total, 71.272, 'total = stage1*0.4 + stage3*0.6');
  assert.equal(score.weights.stage1, 0.4);
  assert.equal(score.weights.stage3, 0.6);
  assert.equal(score.comparison.totalV2, 30);
  assert.equal(score.comparison.delta, 41.272);
  assert.equal(score.comparison.snapshot.comparable, false);
  assert.ok(fs.existsSync(path.join(dir, 'score_v21.json')));
  assert.ok(fs.existsSync(path.join(dir, 'score_v21.txt')));
  assert.equal(JSON.parse(fs.readFileSync(path.join(dir, 'score_v2.json'), 'utf8')).total, 30);
  assert.match(score.provisionalReasons.join(' '), /median of R1\/R2/);

  fs.writeFileSync(path.join(dir, 'stage_3', 'score.json'), JSON.stringify({version: 'stage3-score-v1',
    evidenceComplete: true, total: 40, breakdown: []}));
  await assert.rejects(v21.main(['node', 'score_match_v21.js', dir, '--quiet']), /version/);
  fs.rmSync(root, {recursive: true, force: true});
});

test('v2.1-v3 ledger lives in config.json and leaves the v2 knobs intact', () => {
  const config = loadConfig();
  assert.equal(v21.VERSION, config.total.v2_1.version);
  assert.equal(stage3v21.VERSION, config.stage3.versionV21);
  assert.equal(config.stage3.versionV21, 'stage3-score-v2.1-v3');
  assert.equal(current('total.v2_1.parameters.stage1Weight'), 0.4);
  assert.equal(current('total.v2_1.parameters.stage3Weight'), 0.6);
  assert.equal(current('total.v2_1.parameters.clipMin'), 0);
  assert.equal(current('total.v2_1.parameters.clipMax'), 100);
  assert.equal(current('stage3.v21.parameters.ambush.alpha'), 0.4);
  assert.equal(current('stage3.v21.parameters.ambush.r0'), 0.281238);
  assert.equal(current('stage3.v21.parameters.barrage.r0'), 0.182273);
  assert.equal(current('stage3.v21.parameters.ambushV3.alpha'), 0.4);
  assert.equal(current('stage3.v21.parameters.ambushV3.epsilon'), 0.05);
  assert.equal(current('stage3.v21.parameters.ambushV3.T0'), 3);
  assert.equal(current('stage3.v21.parameters.ambushV3.T_hi'), 21.122);
  assert.equal(current('stage3.v21.parameters.ambushV3.W_floor'), 3);
  assert.equal(current('stage3.v21.parameters.ambushV3.R0'), 0.253601);
  assert.equal(current('stage3.v21.parameters.ambushV3.P_max'), 50);
  assert.equal(current('stage3.v21.parameters.barrageV3.alpha'), 0.4);
  assert.equal(current('stage3.v21.parameters.barrageV3.epsilon'), 0.03);
  assert.equal(current('stage3.v21.parameters.barrageV3.T0'), 8);
  assert.equal(current('stage3.v21.parameters.barrageV3.T_hi'), 23.152);
  assert.equal(current('stage3.v21.parameters.barrageV3.W_floor'), 2);
  assert.equal(current('stage3.v21.parameters.barrageV3.R0'), 0.237905);
  assert.equal(current('stage3.v21.parameters.barrageV3.P_max'), 40);
  assert.equal(current('stage3.parameters.fundsV3.exponent'), 0.5);
  assert.equal(v21.combined(50, 80, 0.4, 0.6), 68);
  assert.equal(v21.combined(80, 100), 92);
  assert.equal(v21.combined(10, 0), 4);
  assert.equal(v2.combined(50, 80, 0.6), 42);
});

test('stage3-v2 defaults stay untouched by the v2.1-v3 parameters', () => {
  const score = stage3.scoreEvents([], {durationMs: 600000, complete: true});
  assert.equal(stage3.VERSION, loadConfig().stage3.version);
  assert.equal(score.breakdown.find(row => row.family === 'STAGE3_FUNDS').cap,
    current('stage3.parameters.funds.Cap'));
});

test('funds v3 weights the three windows 0.55 / 0.40 / 0.05', () => {
  const result = funds.fundsV3(seriesAt(101, [{second: 0, funds: 4000}, {second: 25, funds: 4000},
    {second: 75, funds: 1000}, {second: 100, funds: 1000}], 100));
  assert.deepEqual(result.windowWeights, [0.55, 0.4, 0.05]);
  assert.equal(result.k, 0.6028);
  // 0.55·0.3846 + 0.40·0.8889 + 0.05·0.7143
  assert.equal(Number(result.windows.reduce((sum, window, index) =>
    sum + result.windowWeights[index] * window.k, 0).toFixed(4)), 0.6028);
  assert.equal(result.deduction, 18.907);
});

test('ambush v3 drops hits taken before the unit had been idle long enough', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'rwx-v3-idlems-'));
  // One buffer, three hits taken after 6 s / 1.5 s / 5 s of continuous idleness.
  const rows = [
    {kind: 'damage', timeMs: 10000, hpLoss: 100, shieldLoss: 0,
      victim: {id: 1, type: 'c_tank', side: 'self', building: false},
      attacker: {type: 'c_tank', side: 'enemy', building: false}},
    {kind: 'damage', timeMs: 12000, hpLoss: 100, shieldLoss: 0,
      victim: {id: 1, type: 'c_tank', side: 'self', building: false},
      attacker: {type: 'c_tank', side: 'enemy', building: false}},
    {kind: 'damage', timeMs: 16000, hpLoss: 100, shieldLoss: 0,
      victim: {id: 1, type: 'c_tank', side: 'self', building: false},
      attacker: {type: 'c_tank', side: 'enemy', building: false}},
    {kind: 'stage3_ambush', phase: 'hit', eventId: 'A1', unitId: 1, timeMs: 10000, idleMs: 6000,
      type: 'c_tank', deltaHp: 100, deltaShield: 0, maxHp: 1000, maxShield: 0, cost: 1000},
    {kind: 'stage3_ambush', phase: 'hit', eventId: 'A1', unitId: 1, timeMs: 12000, idleMs: 1500,
      type: 'c_tank', deltaHp: 100, deltaShield: 0, maxHp: 1000, maxShield: 0, cost: 1000},
    {kind: 'stage3_ambush', phase: 'hit', eventId: 'A1', unitId: 1, timeMs: 16000, idleMs: 5000,
      type: 'c_tank', deltaHp: 100, deltaShield: 0, maxHp: 1000, maxShield: 0, cost: 1000},
    {kind: 'stage3_ambush', phase: 'close', eventId: 'A1', unitId: 1, toMs: 18000, idleMs: 7000,
      died: false, complete: true, maxHp: 1000, maxShield: 0, cost: 1000, type: 'c_tank'}];
  writeTelemetry(dir, rows);
  const file = path.join(dir, 'telemetry.jsonl');

  const four = await stage3v21.readTelemetryV3(file, 0.4, 4000);
  assert.equal(four.ambush[0].N, 2, 'the 1.5 s hit happened too early in the idle period');
  assert.equal(four.droppedShortIdle, 1);
  assert.equal(four.minIdleMs, 4000);

  const noFloor = await stage3v21.readTelemetryV3(file, 0.4, null);
  assert.equal(noFloor.ambush[0].N, 3, 'no floor means every hit stays');
  assert.equal(noFloor.droppedShortIdle, 0);

  // Telemetry collected before the field existed must keep its old behaviour.
  const old = rows.map(row => row.kind === 'stage3_ambush'
    ? Object.fromEntries(Object.entries(row).filter(([key]) => key !== 'idleMs')) : row);
  writeTelemetry(dir, old);
  const missing = await stage3v21.readTelemetryV3(file, 0.4, 4000);
  assert.equal(missing.ambush[0].N, 3);
  assert.equal(missing.droppedShortIdle, 0);
});