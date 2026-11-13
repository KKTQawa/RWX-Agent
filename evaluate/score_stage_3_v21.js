#!/usr/bin/env node
'use strict';
/**
 * Stage-3 v2.1（items v3）: ambush v3, barrage v3, grinder v2 (reused) and funds v3.
 *
 * v3 counts reaction opportunities, not damage share:
 *
 *   ambush v3   M1 = Σ w over admitted idle events (fast reactions included)
 *               R1 = Σ w · u' · sev / (M1 + W_floor)
 *   barrage v3  M2 = Σ w over admitted artillery events (short bursts included)
 *               R2 = Σ w · u' · sev / (M2 + W_floor_b)
 *
 * It never rewrites `stage_3/score.json`, `stage_3/events.jsonl` or `score_v2.json`.
 * The v2 damage-share values are kept as diagnostics only.
 */
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const {current, loadConfig} = require('./config');
const {economySeconds} = require('./score_stage_2');
const {fundsV3} = require('./funds_v3');

const CONFIG = loadConfig();
const VERSION = CONFIG.stage3.versionV21;
const AIR = new Set(['aaBeamGunship', 'amphibiousJet', 'bomber', 'c_helicopter', 'c_interceptor',
  'dropship', 'gunShip', 'heavyInterceptor', 'lightGunship', 'missileAirship',
  'experimentalGunship', 'mechFlying']);
const WATER = new Set(['attackSubmarine', 'battleShip', 'gunBoat', 'heavyAAShip', 'heavyBattleship',
  'heavySub', 'lightSub', 'missileShip', 'carrier']);
const round = (value, digits = 3) => value == null || !Number.isFinite(value)
  ? null : Number(value.toFixed(digits));
const clip = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
const median = values => {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b), middle = sorted.length >> 1;
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};
const quantile = (values, p) => {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b), at = (sorted.length - 1) * p, index = Math.floor(at);
  return sorted[index] + (sorted[Math.min(index + 1, sorted.length - 1)] - sorted[index]) * (at - index);
};

function parameters() {
  return {
    ambushV3: current('stage3.v21.parameters.ambushV3', CONFIG),
    barrageV3: current('stage3.v21.parameters.barrageV3', CONFIG),
    ambushV2: current('stage3.v21.parameters.ambush', CONFIG),
    barrageV2: current('stage3.v21.parameters.barrage', CONFIG),
    funds: {incomeFieldPerSecond: current('stage3.parameters.funds.incomeFieldPerSecond', CONFIG),
      singleMax: current('stage3.parameters.fundsV3.SingleMax', CONFIG),
      exponent: current('stage3.parameters.fundsV3.exponent', CONFIG),
      windowSplits: current('stage3.parameters.fundsV3.windowSplits', CONFIG),
      windowWeights: current('stage3.parameters.fundsV3.windowWeights', CONFIG)},
  };
}

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
}

function telemetryFile(dir) {
  return [path.join(dir, 'prepared', 'telemetry.jsonl'), path.join(dir, 'resim', 'telemetry.jsonl')]
    .find(file => fs.existsSync(file)) || null;
}

function landVictim(type) {
  return !AIR.has(type) && !WATER.has(type);
}

/**
 * One pass over telemetry: v3 ambush/barrage records plus v2 X1/X2 diagnostics.
 * An ambush hit is admitted only when its attacker is an enemy mobile unit and the victim
 * is one of our land mobile units. Barrage records keep the last hit time so T_j can stop
 * at the last shell rather than at the buffer's later expiry.
 */
async function readTelemetryV3(file, alpha = 0.4) {
  const damage = new Map(), ambushHits = new Map(), ambushCloses = new Map();
  const barrageHits = new Map(), barrageCloses = new Map();
  let X1 = 0, X2 = 0, damageRows = 0, unmatched = 0;
  const lines = readline.createInterface({input: fs.createReadStream(file), crlfDelay: Infinity});
  for await (const line of lines) {
    if (!line.trim()) continue;
    const row = JSON.parse(line);
    if (row.kind === 'damage' && row.victim && row.attacker) {
      damageRows++;
      damage.set(`${row.victim.id}|${row.timeMs}|${row.hpLoss}|${row.shieldLoss}`, row.attacker);
      const amount = Number(row.hpLoss || 0) + alpha * Number(row.shieldLoss || 0);
      const victim = row.victim, attacker = row.attacker;
      if (victim.side === 'self' && !victim.building && landVictim(victim.type)
        && attacker.side === 'enemy' && !attacker.building) X1 += amount;
      if (victim.side === 'self' && victim.building && attacker.side === 'enemy' && !attacker.building)
        X2 += amount;
    } else if (row.kind === 'stage3_ambush') {
      if (row.phase === 'hit') {
        if (!ambushHits.has(row.eventId)) ambushHits.set(row.eventId, []);
        ambushHits.get(row.eventId).push(row);
      } else if (row.phase === 'close') ambushCloses.set(row.eventId, row);
    } else if (row.kind === 'stage3_barrage') {
      if (row.phase === 'hit') {
        if (!barrageHits.has(row.eventId)) barrageHits.set(row.eventId, []);
        barrageHits.get(row.eventId).push(row);
      } else if (row.phase === 'close') barrageCloses.set(row.eventId, row);
    }
  }

  const ambush = [];
  for (const [id, list] of ambushHits) {
    const kept = [];
    for (const hit of list) {
      const attacker = damage.get(`${hit.unitId}|${hit.timeMs}|${hit.deltaHp}|${hit.deltaShield}`);
      if (!attacker) { unmatched++; continue; }
      if (attacker.building) continue;
      if (!landVictim(hit.type)) continue;
      kept.push(hit);
    }
    if (!kept.length) continue;
    const close = ambushCloses.get(id);
    const first = kept.reduce((a, b) => b.timeMs < a.timeMs ? b : a);
    const last = kept.reduce((a, b) => b.timeMs > a.timeMs ? b : a);
    const endMs = close ? Number(close.toMs) : last.timeMs;
    ambush.push({id, unitId: first.unitId, type: first.type, startMs: first.timeMs, endMs,
      T: round(Math.max(0, endMs - first.timeMs) / 1000, 3),
      D_hp: round(kept.reduce((sum, hit) => sum + Number(hit.deltaHp || 0), 0), 3),
      D_sh: round(kept.reduce((sum, hit) => sum + Number(hit.deltaShield || 0), 0), 3),
      N: kept.length,
      maxHp: Number(close ? close.maxHp : first.maxHp) || 0,
      maxShield: Number(close ? close.maxShield : first.maxShield) || 0,
      cost: Number(close ? close.cost : first.cost) || 0,
      died: Boolean(close && close.died),
      complete: close ? close.complete !== false : false,
      closeReason: close ? close.closeReason : 'NO_CLOSE'});
  }

  const barrage = [];
  for (const [id, list] of barrageHits) {
    const close = barrageCloses.get(id);
    const first = list.reduce((a, b) => b.timeMs < a.timeMs ? b : a);
    const last = list.reduce((a, b) => b.timeMs > a.timeMs ? b : a);
    const destroyed = Boolean(close && close.destroyed);
    const endMs = destroyed ? Number(close.toMs) : last.timeMs;
    barrage.push({id, type: first.type, startMs: first.timeMs, lastMs: last.timeMs, endMs,
      T: round(Math.max(0, endMs - first.timeMs) / 1000, 3),
      N: list.length,
      D_hp: round(list.reduce((sum, hit) => sum + Number(hit.deltaHp || 0), 0), 3),
      D_sh: round(list.reduce((sum, hit) => sum + Number(hit.deltaShield || 0), 0), 3),
      maxHp: Number(close ? close.maxHp : first.maxHp) || 0,
      maxShield: Number(close ? close.maxShield : first.maxShield) || 0,
      cost: Number(close ? close.cost : first.cost) || 0,
      destroyed,
      complete: close ? close.complete !== false : false,
      closeReason: close ? close.closeReason : 'NO_CLOSE'});
  }
  return {ambush, barrage, X1: round(X1), X2: round(X2), damageRows, unmatched};
}

/** v2 damage-share records, kept only for the diagnostic bypass. */
function ambushRecords(records, p) {
  return records.filter(record => record.died || record.T > p.T0).map(record => {
    const E = record.D_hp + p.alpha * record.D_sh;
    const H = record.maxHp + p.alpha * record.maxShield;
    const base = record.died ? H : Math.min(E, H);
    const loss = base * (1 + p.delta * (record.died ? 1 : 0));
    const Tf = 1 + p.gamma * clip((record.T - p.T0) / p.T_span, 0, 1);
    const w = clip(Math.sqrt(Math.max(0, record.cost) / p.C_w), p.w_lo, p.w_hi);
    return {...record, E: round(E), H: round(H), base: round(base), loss: round(loss),
      Tf: round(Tf), w: round(w, 4), contribution: round(w * loss * Tf)};
  });
}

function barrageRecords(records, p) {
  return records.filter(record => record.N >= 2 || record.destroyed).map(record => {
    const E = record.D_hp + p.alpha * record.D_sh;
    const H = record.maxHp + p.alpha * record.maxShield;
    const base = record.destroyed ? H : Math.min(E, H);
    const loss = base * (1 + p.delta * (record.destroyed ? 1 : 0));
    const w = clip(Math.sqrt(Math.max(0, record.cost) / p.C_w), p.w_lo, p.w_hi);
    return {...record, E: round(E), H: round(H), base: round(base), loss: round(loss),
      w: round(w, 4), contribution: round(w * loss)};
  });
}

function scoreItem(records, exposure, p) {
  const numerator = records.reduce((sum, record) => sum + record.contribution, 0);
  const floor = p.X_floorMultiplier * median(records.map(record => record.H));
  const denominator = exposure + floor;
  const r = denominator > 0 ? numerator / denominator : 0;
  const deduction = p.P_max * (1 - Math.exp(-r / p.r0));
  return {numerator: round(numerator), exposure: round(exposure), X_floor: round(floor), r: round(r, 6),
    r0: p.r0, P_max: p.P_max, deduction: round(clip(deduction, 0, p.P_max)), records};
}

function latency(record, p) {
  const T = Math.max(0, Number(record.T) || 0);
  const u = clip((Math.log1p(T) - Math.log1p(p.T0)) / (Math.log1p(p.T_hi) - Math.log1p(p.T0)), 0, 1);
  const uPrime = Math.min(1, u + p.delta * (record.died || record.destroyed ? 1 : 0));
  return {T, u, uPrime};
}

function valueWeight(cost, p) {
  return clip(Math.sqrt(Math.max(0, Number(cost) || 0) / p.C_w), p.w_lo, p.w_hi);
}

/**
 * Ambush v3: every admitted event contributes its value weight to M1, including fast
 * reactions (u=0) and one-shot deaths (u'=delta). The numerator only counts the weighted
 * latency/severity of those opportunities.
 */
function scoreAmbushV3(records, p) {
  const rows = records.map(record => {
    const E = record.D_hp + p.alpha * record.D_sh;
    const H = record.maxHp + p.alpha * record.maxShield;
    const ratio = H > 0 ? E / H : 0;
    const admitted = ratio >= p.epsilon || record.died;
    const {T, u, uPrime} = latency(record, p);
    const sev = record.died ? 1 : clip(ratio, p.s_lo, 1);
    const w = valueWeight(record.cost, p);
    const s = admitted ? w * uPrime * sev : 0;
    return {...record, E: round(E), H: round(H), ratio: round(ratio, 4), admitted,
      T: round(T, 3), u: round(u, 4), uPrime: round(uPrime, 4), sev: round(sev, 4),
      w: round(w, 4), s: round(s, 4), _w: w, _s: s};
  });
  const admitted = rows.filter(row => row.admitted);
  const M = admitted.reduce((sum, row) => sum + row._w, 0);
  const numerator = admitted.reduce((sum, row) => sum + row._s, 0);
  const R = M > 0 ? numerator / (M + p.W_floor) : 0;
  const deduction = p.P_max * (1 - Math.exp(-R / p.R0));
  const times = admitted.map(row => row.T);
  return {events: rows.length, admitted: admitted.length,
    hits: rows.reduce((sum, row) => sum + Number(row.N || 0), 0),
    admittedHits: admitted.reduce((sum, row) => sum + Number(row.N || 0), 0),
    M: round(M), W_floor: p.W_floor,
    numerator: round(numerator), R: round(R, 6), r: round(R, 6), R0: p.R0, P_max: p.P_max,
    deduction: round(clip(deduction, 0, p.P_max)),
    fast: admitted.filter(row => row.T < p.T0).length,
    fastShare: admitted.length ? round(admitted.filter(row => row.T < p.T0).length / admitted.length, 4) : 0,
    died: admitted.filter(row => row.died).length,
    saturated: admitted.filter(row => row.u >= 0.999).length,
    tP50: round(quantile(times, .5)), tP90: round(quantile(times, .9)),
    lowConfidence: admitted.length < 5, floorFlag: M < p.W_floor,
    T0: p.T0, T_hi: p.T_hi, epsilon: p.epsilon,
    records: admitted.map(({_w, _s, ...row}) => row)};
}

/** Barrage v3: T_j ends at the last shell (or destruction time); short bursts stay in M2. */
function scoreBarrageV3(records, p) {
  const rows = records.map(record => {
    const E = record.D_hp + p.alpha * record.D_sh;
    const H = record.maxHp + p.alpha * record.maxShield;
    const ratio = H > 0 ? E / H : 0;
    const admitted = (record.N >= 2 || record.destroyed) && (ratio >= p.epsilon || record.destroyed);
    const {T, u, uPrime} = latency(record, p);
    const sev = record.destroyed ? 1 : clip(ratio, p.s_lo, 1);
    const w = valueWeight(record.cost, p);
    const s = admitted ? w * uPrime * sev : 0;
    return {...record, E: round(E), H: round(H), ratio: round(ratio, 4), admitted,
      T: round(T, 3), u: round(u, 4), uPrime: round(uPrime, 4), sev: round(sev, 4),
      w: round(w, 4), s: round(s, 4), _w: w, _s: s};
  });
  const admitted = rows.filter(row => row.admitted);
  const M = admitted.reduce((sum, row) => sum + row._w, 0);
  const numerator = admitted.reduce((sum, row) => sum + row._s, 0);
  const R = M > 0 ? numerator / (M + p.W_floor) : 0;
  const deduction = p.P_max * (1 - Math.exp(-R / p.R0));
  const times = admitted.map(row => row.T);
  return {events: rows.length, admitted: admitted.length,
    hits: rows.reduce((sum, row) => sum + Number(row.N || 0), 0),
    admittedHits: admitted.reduce((sum, row) => sum + Number(row.N || 0), 0),
    M: round(M), W_floor: p.W_floor,
    numerator: round(numerator), R: round(R, 6), r: round(R, 6), R0: p.R0, P_max: p.P_max,
    deduction: round(clip(deduction, 0, p.P_max)),
    destroyed: admitted.filter(row => row.destroyed).length,
    saturated: admitted.filter(row => row.u >= 0.999).length,
    tP50: round(quantile(times, .5)), tP90: round(quantile(times, .9)),
    lowConfidence: admitted.length < 3, floorFlag: M < p.W_floor,
    T0: p.T0, T_hi: p.T_hi, epsilon: p.epsilon,
    records: admitted.map(({_w, _s, ...row}) => row)};
}

function grinderOf(stage3) {
  const family = stage3.breakdown?.find(row => row.family === 'STAGE3_GRINDER');
  if (!family) throw Error('Stage-3 v2 score has no STAGE3_GRINDER family');
  return {deduction: Number(family.deduction || 0), cap: Number(family.cap || 100),
    raw: Number(family.raw || 0)};
}

function legacyOf(ambushRecordsRaw, barrageRecordsRaw, scanned, p) {
  const ambush = scoreItem(ambushRecords(ambushRecordsRaw, p.ambushV2), scanned.X1, p.ambushV2);
  const barrage = scoreItem(barrageRecords(barrageRecordsRaw, p.barrageV2), scanned.X2, p.barrageV2);
  return {ambush: {deduction: ambush.deduction, numerator: ambush.numerator, exposure: ambush.exposure,
    X_floor: ambush.X_floor, r: ambush.r, records: ambush.records.length},
  barrage: {deduction: barrage.deduction, numerator: barrage.numerator, exposure: barrage.exposure,
    X_floor: barrage.X_floor, r: barrage.r, records: barrage.records.length}};
}

async function scoreStage3V21(dir, options = {}) {
  const p = parameters();
  const stage3 = readJson(path.join(dir, 'stage_3', 'score.json'));
  const telemetry = options.telemetry || telemetryFile(dir);
  if (!telemetry) throw Error('telemetry.jsonl is missing');
  const economy = options.economy || [path.join(dir, 'prepared', 'economy.log'),
    path.join(dir, 'resim', 'economy.log')].find(file => fs.existsSync(file));
  if (!economy) throw Error('ECONOMY_EVIDENCE_MISSING');
  const scanned = await readTelemetryV3(telemetry, p.ambushV2.alpha);
  const ambush = scoreAmbushV3(scanned.ambush, p.ambushV3);
  const barrage = scoreBarrageV3(scanned.barrage, p.barrageV3);
  const legacy = legacyOf(scanned.ambush, scanned.barrage, scanned, p);
  let samples = economySeconds(economy);
  const cutMs = Number.isFinite(options.cutMs) ? options.cutMs
    : (Number.isFinite(stage3.durationSeconds) ? Math.round(stage3.durationSeconds * 1000) : null);
  if (Number.isFinite(cutMs)) samples = samples.slice(0, Math.floor(cutMs / 1000) + 1);
  const funds = fundsV3(samples, p.funds);
  if (!funds.available) throw Error(funds.reason);
  const grinder = grinderOf(stage3);
  const deduction = round(ambush.deduction + barrage.deduction + grinder.deduction + funds.deduction);
  return {version: VERSION, stage3Version: stage3.version, itemVersions: {ambush: 'v3', barrage: 'v3',
    grinder: 'v2', funds: 'v3'}, durationSeconds: stage3.durationSeconds,
    ambush, barrage, legacy, grinder, funds, deduction, total: round(Math.max(0, 100 - deduction)),
    breakdown: [
      {family: 'STAGE3_AMBUSH_V3', deduction: ambush.deduction, P_max: ambush.P_max,
        M: ambush.M, R: ambush.R, R0: ambush.R0, events: ambush.events, admitted: ambush.admitted},
      {family: 'STAGE3_BARRAGE_V3', deduction: barrage.deduction, P_max: barrage.P_max,
        M: barrage.M, R: barrage.R, R0: barrage.R0, events: barrage.events, admitted: barrage.admitted},
      {family: 'STAGE3_GRINDER', deduction: grinder.deduction, cap: grinder.cap},
      {family: 'STAGE3_FUNDS_V3', deduction: funds.deduction, cap: funds.singleMax, k: funds.k}],
    diagnostics: {damageRows: scanned.damageRows, unmatchedHits: scanned.unmatched,
      ambushEvents: ambush.events, admittedAmbush: ambush.admitted, fastAmbush: ambush.fast,
      ambushLowConfidence: ambush.lowConfidence, ambushFloorFlag: ambush.floorFlag,
      barrageEvents: barrage.events, admittedBarrage: barrage.admitted,
      barrageLowConfidence: barrage.lowConfidence, barrageFloorFlag: barrage.floorFlag,
      X1: scanned.X1, X2: scanned.X2, legacyR1: legacy.ambush.r, legacyR2: legacy.barrage.r}};
}

function report(score) {
  const a = score.ambush, b = score.barrage, g = score.grinder, f = score.funds;
  return [`第三阶段 v2.1-v3（${score.version}）`, '='.repeat(52),
    `偷袭 v3   扣 ${a.deduction} / ${a.P_max}  (事件 ${a.admitted}/${a.events}，M ${a.M}，R1 ${a.R}，R0 ${a.R0}，快速 ${a.fast})`,
    `偷家 v3   扣 ${b.deduction} / ${b.P_max}  (事件 ${b.admitted}/${b.events}，M ${b.M}，R2 ${b.R}，R0 ${b.R0}，摧毁 ${b.destroyed})`,
    `绞肉机    扣 ${g.deduction} / ${g.cap}（沿用 v2）`,
    `资金 v3   扣 ${f.deduction} / ${f.singleMax}  (K ${f.k})`,
    `对照 v2   偷袭 ${score.legacy.ambush.deduction}（r1 ${score.legacy.ambush.r}）、` +
      `偷家 ${score.legacy.barrage.deduction}（r2 ${score.legacy.barrage.r}）`,
    `合计扣 ${score.deduction}，Stage3 ${score.total}`, ''].join('\n');
}

async function main(argv = process.argv) {
  const args = argv.slice(2), target = args.shift();
  if (!target) throw Error('Usage: node evaluate/score_stage_3_v21.js <match dir> [--out dir] [--quiet]');
  let out = null, quiet = false, options = {};
  while (args.length) {
    const flag = args.shift();
    if (flag === '--out') out = path.resolve(args.shift());
    else if (flag === '--quiet') quiet = true;
    else if (flag === '--telemetry') options.telemetry = path.resolve(args.shift());
    else if (flag === '--economy') options.economy = path.resolve(args.shift());
    else if (flag === '--cut-ms') options.cutMs = Number(args.shift());
    else throw Error(`Unknown option ${flag}`);
  }
  const dir = path.resolve(target);
  const score = await scoreStage3V21(dir, options);
  out ||= path.join(dir, 'stage_3_v21');
  fs.mkdirSync(out, {recursive: true});
  fs.writeFileSync(path.join(out, 'score.json'), JSON.stringify(score, null, 2) + '\n');
  fs.writeFileSync(path.join(out, 'score.txt'), report(score));
  if (!quiet) console.log(report(score));
  return score;
}

if (require.main === module) main().catch(error => {
  console.error(error.stack || error.message); process.exitCode = 1;
});
module.exports = {VERSION, AIR, WATER, parameters, readTelemetryV3, ambushRecords, barrageRecords,
  scoreItem, scoreAmbushV3, scoreBarrageV3, scoreStage3V21, report, main};
