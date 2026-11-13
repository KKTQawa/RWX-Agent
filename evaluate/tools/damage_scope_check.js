#!/usr/bin/env node
'use strict';
/**
 * Check whether the Stage-3 ambush/barrage damage is covered by the two combat-damage
 * definitions used for the new audit:
 *
 *   A = our land mobile units hit by enemy non-building units   (hpLoss + shieldLoss)
 *   B = our buildings hit by enemy units                        (hpLoss + shieldLoss)
 *
 * It joins the scoreable `stage_3/events.jsonl` events with the raw `damage` rows in
 * `prepared/telemetry.jsonl` on (victim id, time, hpLoss, shieldLoss), so every scored event is
 * decomposed by victim domain and attacker kind. It is read-only.
 *
 * Usage: node evaluate/tools/damage_scope_check.js [--root evaluate/output] [--json]
 */
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');

const ROOT = path.resolve(__dirname, '..', '..');
const DEFAULT_OUTPUT = path.join(ROOT, 'evaluate', 'output');
// UnitTypeEnum / engine class hierarchy: AirUnit subclasses and WaterUnit subclasses. Everything
// else that is `building=false` is a land mobile unit; HoverLandUnit types (hoverTank,
// heavyHoverTank, hovercraft) belong to land.
const AIR = new Set(['aaBeamGunship', 'amphibiousJet', 'bomber', 'c_helicopter', 'c_interceptor',
  'dropship', 'gunShip', 'heavyInterceptor', 'lightGunship', 'missileAirship',
  'experimentalGunship', 'mechFlying']);
const WATER = new Set(['attackSubmarine', 'battleShip', 'gunBoat', 'heavyAAShip', 'heavyBattleship',
  'heavySub', 'lightSub', 'missileShip', 'carrier']);
const ARTILLERY = new Set(['c_artillery', 'heavyArtillery', 'mechArtillery']);
const round = value => Number(Number(value).toFixed(1));

function matches(root) {
  return fs.readdirSync(root, {withFileTypes: true})
    .filter(entry => entry.isDirectory() && !entry.name.startsWith('_') && entry.name !== 'micro')
    .map(entry => path.join(root, entry.name))
    .filter(dir => fs.existsSync(path.join(dir, 'stage_3', 'events.jsonl')) &&
      fs.existsSync(path.join(dir, 'prepared', 'telemetry.jsonl')));
}

function scoreable(dir) {
  const ambush = new Set(), barrage = new Set();
  for (const line of fs.readFileSync(path.join(dir, 'stage_3', 'events.jsonl'), 'utf8').split(/\r?\n/)) {
    if (!line.trim()) continue;
    const event = JSON.parse(line);
    if (event.scoreable === false) continue;
    if (event.type === 'STAGE3_AMBUSH') ambush.add(event.id);
    else if (event.type === 'STAGE3_BARRAGE') barrage.add(event.id);
  }
  return {ambush, barrage};
}

async function scan(dir) {
  const events = scoreable(dir);
  const damage = new Map(), ambushHits = [], barrageHits = [];
  const stream = fs.createReadStream(path.join(dir, 'prepared', 'telemetry.jsonl'));
  const lines = readline.createInterface({input: stream, crlfDelay: Infinity});
  let A = 0, BUnits = 0, BAll = 0;
  for await (const line of lines) {
    if (!line.trim()) continue;
    const row = JSON.parse(line);
    if (row.kind === 'damage' && row.victim && row.attacker) {
      const key = `${row.victim.id}|${row.timeMs}|${row.hpLoss}|${row.shieldLoss}`;
      damage.set(key, row.attacker);
      const amount = Number(row.hpLoss || 0) + Number(row.shieldLoss || 0);
      const victim = row.victim, attacker = row.attacker;
      if (victim.side === 'self' && !victim.building && !AIR.has(victim.type) && !WATER.has(victim.type)
        && attacker.side === 'enemy' && !attacker.building) A += amount;
      if (victim.side === 'self' && victim.building && attacker.side === 'enemy' && !attacker.building)
        BUnits += amount;
      if (victim.side === 'self' && victim.building && attacker.side === 'enemy') BAll += amount;
    } else if (row.kind === 'stage3_ambush' && row.phase === 'hit' && events.ambush.has(row.eventId)) {
      ambushHits.push(row);
    } else if (row.kind === 'stage3_barrage' && row.phase === 'hit' && events.barrage.has(row.eventId)) {
      barrageHits.push(row);
    }
  }
  let ambush = 0, insideA = 0, air = 0, building = 0, overlap = 0;
  for (const hit of ambushHits) {
    const amount = Number(hit.deltaHp || 0) + Number(hit.deltaShield || 0);
    ambush += amount;
    const attacker = damage.get(`${hit.unitId}|${hit.timeMs}|${hit.deltaHp}|${hit.deltaShield}`);
    const airborne = AIR.has(hit.type) || WATER.has(hit.type);
    const fromBuilding = Boolean(attacker && attacker.building);
    if (airborne) air += amount;
    if (fromBuilding) building += amount;
    if (airborne && fromBuilding) overlap += amount;
    if (!airborne && !fromBuilding) insideA += amount;
  }
  let barrage = 0, badAttacker = 0, badVictim = 0;
  for (const hit of barrageHits) {
    const amount = Number(hit.deltaHp || 0) + Number(hit.deltaShield || 0);
    barrage += amount;
    if (!ARTILLERY.has(hit.attackerType)) badAttacker += amount;
    const attacker = damage.get(`${hit.unitId}|${hit.timeMs}|${hit.deltaHp}|${hit.deltaShield}`);
    if (attacker && attacker.building) badVictim += amount;
  }
  return {match: path.basename(dir), A: round(A), BUnits: round(BUnits), BAll: round(BAll),
    ambush: round(ambush), ambushInsideA: round(insideA), ambushAir: round(air),
    ambushBuilding: round(building), ambushOverlap: round(overlap),
    ambushOutsideA: round(ambush - insideA), barrage: round(barrage),
    barrageBadAttacker: round(badAttacker), barrageBadVictim: round(badVictim)};
}

function report(rows) {
  const header = ['match', 'ambush', 'inA', 'A', 'air', 'bldg', 'barrage', 'B_unit', 'B_all'];
  const line = row => [row.match, row.ambush, row.ambushInsideA, row.A, row.ambushAir,
    row.ambushBuilding, row.barrage, row.BUnits, row.BAll].join('\t');
  const sum = key => round(rows.reduce((total, row) => total + row[key], 0));
  return [header.join('\t'), ...rows.map(line), '',
    ['TOTAL', sum('ambush'), sum('ambushInsideA'), sum('A'), sum('ambushAir'),
      sum('ambushBuilding'), sum('barrage'), sum('BUnits'), sum('BAll')].join('\t')].join('\n');
}

async function main(argv = process.argv) {
  const args = argv.slice(2);
  let root = DEFAULT_OUTPUT, json = false;
  while (args.length) {
    const flag = args.shift();
    if (flag === '--root') root = path.resolve(args.shift());
    else if (flag === '--json') json = true;
    else throw Error('Usage: node evaluate/tools/damage_scope_check.js [--root <dir>] [--json]');
  }
  const rows = [];
  for (const dir of matches(root)) rows.push(await scan(dir));
  const violations = {
    ambushGreaterThanA: rows.filter(row => row.ambush > row.A + 0.05).map(row => row.match),
    insideAGreaterThanA: rows.filter(row => row.ambushInsideA > row.A + 0.05).map(row => row.match),
    barrageGreaterThanB: rows.filter(row => row.barrage > Math.min(row.BUnits, row.BAll) + 0.05)
      .map(row => row.match),
    ambushOutsideA: rows.filter(row => row.ambushOutsideA > 0).length,
    barrageBadAttacker: rows.filter(row => row.barrageBadAttacker > 0).length,
    barrageBadVictim: rows.filter(row => row.barrageBadVictim > 0).length};
  const result = {schema: 1, rows, violations};
  if (json) console.log(JSON.stringify(result, null, 2));
  else {
    console.log(report(rows));
    console.log(JSON.stringify(violations, null, 2));
  }
  return result;
}

if (require.main === module) main().catch(error => {
  console.error(error.stack || error.message); process.exitCode = 1;
});
module.exports = {AIR, WATER, ARTILLERY, matches, scan, report, main};
