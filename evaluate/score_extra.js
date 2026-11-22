#!/usr/bin/env node
'use strict';
/**
 * Extra (non-total) score: operation tempo / fluency from the native command stream.
 *
 * This is a diagnostic metric, **not** part of `total`. It reads the engine-executed command rows
 * (`kind:"native"`) of the judged seat, turns them into "operations" (one order, not one unit),
 * and measures rate, dead time and rhythm regularity. Definition and parameter rationale:
 * `evaluate/EXTRA_SCORING.md`.
 *
 * Time base: `timeMs` is engine game time, so a pause does not advance it and needs no correction;
 * the scored window comes from `stage_3/summary.json` (`durationMs`), which already ends where the
 * match is decided.
 */
const fs = require('node:fs');
const path = require('node:path');
const readline = require('node:readline');
const {current, loadConfig} = require('./config');

const VERSION = 'extra-fluency-v1';
const PARAMETERS = 'extra.parameters.fluency';

/** Counted commands: every command the judged seat can issue on purpose. `attack` is a switch
 *  because a player-issued attack order and the engine's automatic return fire both look like
 *  "attack" rows to a casual reader; the switch keeps the definition explicit instead of implied. */
const COUNTED = ['action', 'move', 'attackMove', 'guardAt', 'build', 'repair', 'patrol', 'loadInto',
  'reclaim', 'loadUp', 'guard', 'follow', 'stop', 'attack'];

function parameters() {
  const config = loadConfig(), values = current(PARAMETERS, config);
  return {...DEFAULTS, ...values};
}
const DEFAULTS = Object.freeze({
  T: 8, mu0: 6, q0: 0.15, q1: 0.65, c0: 0.4, c1: 0.9,
  alpha: 0.3, spamSeconds: 3, bucketSeconds: 5, skipHeadSeconds: 30,
  smoothWindowSeconds: 30,
  weightDead: 0.5, weightSmooth: 0.5, countAttack: true, positionQuantum: 1,
});
const round = (n, d = 3) => (Number.isFinite(n) ? Number(n.toFixed(d)) : null);
const clip = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
const quant = (value, quantum) => (typeof value === 'number' && Number.isFinite(value)
  ? Math.round(value / Math.max(1e-9, quantum)) : null);

function countedOperations(p) {
  return new Set(COUNTED.filter(op => op !== 'attack' || p.countAttack));
}

/** `before` carries the fields known at issue time, `after` the ones the engine only resolves while
 *  applying (`targetId`, backfilled units) and whether the order changed anything. */
function mergeRow(before, after) {
  const row = {...before};
  if ((!row.units || row.units.length === 0) && after?.units?.length) row.units = after.units;
  for (const key of ['targetId', 'x', 'y', 'buildType', 'count', 'action'])
    if (row[key] == null && after?.[key] != null) row[key] = after[key];
  const results = after?.results ?? [];
  row.applied = results.some(result => result.applied === true);
  row.appliedKnown = results.length > 0;
  return row;
}

/** One order can list many units; identity of an operation is where/what it ordered, never which
 *  unit carried it. `action` and `stop` carry no target point, so the acting unit plus the action id
 *  stands in for it. Material recorded before coordinates were captured cannot tell two orders
 *  apart, and merging on a fabricated point would collapse a whole match into a handful of
 *  "operations": those rows stay one command per operation, skip spam suppression, and the match is
 *  reported as degraded instead of silently scored. */
function identify(row, p) {
  const first = row.units?.[0] ?? '';
  if (row.operation === 'action') {
    const sig = `a:${row.action ?? '-1'}:${first}`;
    return {sig, spamSig: sig, degraded: false};
  }
  if (row.operation === 'stop') {
    const sig = `s:${first}`;
    return {sig, spamSig: sig, degraded: false};
  }
  const pointed = typeof row.x === 'number' && Number.isFinite(row.x)
    && typeof row.y === 'number' && Number.isFinite(row.y);
  if (!pointed) return {sig: `p:${row.nativeId ?? row.timeMs}`, spamSig: null, degraded: true};
  const sig = `p:${quant(row.x, p.positionQuantum)}:${quant(row.y, p.positionQuantum)}:${row.targetId ?? ''}`;
  return {sig, spamSig: sig, degraded: false};
}

/**
 * native rows -> operations.
 *
 * 1. merge `before`/`after` by `nativeId` (one command, one row);
 * 2. expand to unit orders so a box-select and 30 separate clicks are comparable;
 * 3. drop a unit's repeated order for the same signature inside `spamSeconds` (spam suppression);
 * 4. group what is left by (operation, time bucket, signature) and count distinct units;
 * 5. weight a batch order `w = 1 + alpha*ln(n)` so 100 units are worth ~2.4, not 100.
 */
function cleanOperations(rows, p = DEFAULTS) {
  const spamMs = Math.max(0, Number(p.spamSeconds) * 1000);
  const bucketMs = Math.max(0, Number(p.bucketSeconds) * 1000);
  const last = new Map(), groups = new Map();
  const counters = {spamDropped: 0, unitOrders: 0, commands: rows.length, degradedCommands: 0};
  for (const row of rows) {
    const {sig, spamSig, degraded} = identify(row, p);
    if (degraded) counters.degradedCommands++;
    const bucket = bucketMs > 0 ? Math.floor(row.timeMs / bucketMs) : 0;
    const key = `${row.operation}|${bucket}|${sig}`;
    const units = row.units?.length ? row.units : [-1];
    let group = groups.get(key);
    for (const unit of units) {
      if (spamSig != null) {
        const spamKey = `${unit}|${row.operation}|${spamSig}`;
        const previous = last.get(spamKey);
        if (previous != null && row.timeMs - previous < spamMs) { counters.spamDropped++; continue; }
        last.set(spamKey, row.timeMs);
      }
      counters.unitOrders++;
      if (!group) { group = {key, operation: row.operation, sig, t: row.timeMs, x: row.x, y: row.y,
        action: row.action, targetId: row.targetId, buildType: row.buildType, units: new Set(), applied: 0}; groups.set(key, group); }
      group.units.add(unit);
      group.t = Math.min(group.t, row.timeMs);
      if (row.applied) group.applied++;
    }
  }
  const operations = [...groups.values()].map(group => {
    const n = group.units.size;
    return {t: group.t, operation: group.operation, sig: group.sig, units: n,
      weight: round(1 + Number(p.alpha) * Math.log(n)),
      x: group.x, y: group.y, action: group.action, targetId: group.targetId, buildType: group.buildType,
      applied: group.applied};
  }).sort((a, b) => a.t - b.t);
  return {operations, counters};
}

/** Population statistics of the gaps. `cv` needs at least two gaps: a single gap has no spread,
 *  and reporting 0 there would hand an idle match a perfect rhythm score. */
function gapStats(values) {
  const n = values.length;
  if (!n) return {n: 0, mean: null, sd: null, cv: null, burstiness: null};
  const mean = values.reduce((a, b) => a + b, 0) / n;
  const sd = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / n);
  const spread = n >= 2 && mean > 0;
  return {n, mean, sd, cv: spread ? sd / mean : null,
    burstiness: spread && sd + mean > 0 ? (sd - mean) / (sd + mean) : null};
}

/**
 * Coefficient of variation of the weighted operation count per `seconds`-long window.
 *
 * The rhythm term used to be the CV of raw inter-command gaps, which measures how *bursty* the
 * command granularity is: a script that fires a cluster of orders on every poll cycle looks far
 * less regular than a human who dribbles single clicks, even though its strategic tempo is
 * perfectly steady. Binning first measures tempo instead of click granularity, so a script that
 * plays evenly is rewarded, and a player that sits idle for a minute still stands out.
 *
 * Returns null when the window is too short to hold two bins, or nothing was ordered.
 */
function windowCv(operations, startMs, endMs, seconds) {
  const width = Number(seconds) * 1000;
  if (!(width > 0)) return null;
  const bins = Math.floor(Math.max(0, endMs - startMs) / width);
  if (bins < 2) return null;
  const counts = new Array(bins).fill(0);
  for (const op of operations) {
    const index = Math.floor((op.t - startMs) / width);
    if (index >= 0 && index < bins) counts[index] += op.weight;
  }
  const mean = counts.reduce((a, b) => a + b, 0) / bins;
  if (!(mean > 0)) return null;
  const sd = Math.sqrt(counts.reduce((a, b) => a + (b - mean) ** 2, 0) / bins);
  return {cv: sd / mean, bins, meanPerWindow: mean, counts};
}

/**
 * Fluency from the cleaned operation timeline.
 *
 * `S_rate` is a multiplicative gate so a very slow but very regular player cannot buy the score
 * back; `S_dead` (share of time spent inside gaps longer than `T`) and `S_smooth` (windowed CV) split
 * the remainder. Head/tail edges are included in the idle share: with a handful of operations per
 * match, dropping them would hide exactly the "sat still for two minutes" case.
 */
function fluencyScore(operations, window, options = {}) {
  const p = {...parameters(), ...options};
  const startMs = Number(window.startMs ?? 0);
  const endMs = Number(window.endMs ?? startMs);
  const span = Math.max(0, (endMs - startMs) / 1000);
  const weighted = operations.reduce((sum, op) => sum + op.weight, 0);
  const mu = span > 0 ? (weighted / span) * 60 : 0;
  const internal = [];
  for (let i = 1; i < operations.length; i++) internal.push((operations[i].t - operations[i - 1].t) / 1000);
  const edges = [];
  if (operations.length) {
    edges.push((operations[0].t - startMs) / 1000, (endMs - operations[operations.length - 1].t) / 1000);
  } else {
    edges.push(span);
  }
  const idle = Math.max(0, Number(p.T));
  const idleSeconds = [...edges, ...internal].filter(gap => gap > idle).reduce((a, gap) => a + gap, 0);
  const q = span > 0 ? Math.min(1, idleSeconds / span) : 0;
  const stats = gapStats(internal);
  const smoothWidth = Number(p.smoothWindowSeconds);
  const windowed = smoothWidth > 0 ? windowCv(operations, startMs, endMs, smoothWidth) : null;
  // `smoothWindowSeconds: 0` keeps the old gap-based term available for diagnostics.
  const cv = smoothWidth > 0 ? windowed?.cv ?? null : stats.cv;
  const smoothBasis = operations.length === 0 ? 'no_operations'
    : smoothWidth > 0 ? (windowed ? 'window_cv' : 'insufficient_windows')
      : (stats.cv == null ? 'insufficient_gaps' : 'gap_cv');
  const S_rate = 1 - Math.exp(-mu / Math.max(1e-9, Number(p.mu0)));
  const S_dead = clip(1 - (q - Number(p.q0)) / Math.max(1e-9, Number(p.q1) - Number(p.q0)), 0, 1);
  const S_smooth = cv == null ? 0
    : clip(1 - (cv - Number(p.c0)) / Math.max(1e-9, Number(p.c1) - Number(p.c0)), 0, 1);
  const weightDead = Number(p.weightDead), weightSmooth = Number(p.weightSmooth);
  const blend = weightDead + weightSmooth > 0
    ? (weightDead * S_dead + weightSmooth * S_smooth) / (weightDead + weightSmooth) : 0;
  const fluency = 100 * S_rate * blend;
  const longest = [...internal.map((gap, index) => ({fromMs: operations[index].t, toMs: operations[index + 1].t, gap})),
    ...(operations.length ? [{fromMs: startMs, toMs: operations[0].t, gap: edges[0]},
      {fromMs: operations[operations.length - 1].t, toMs: endMs, gap: edges[1]}] : [{fromMs: startMs, toMs: endMs, gap: span}])]
    .filter(item => item.gap > 0).sort((a, b) => b.gap - a.gap).slice(0, 5)
    .map(item => ({fromMs: Math.round(item.fromMs), toMs: Math.round(item.toMs), gapSeconds: round(item.gap)}));
  return {
    fluency: round(fluency), components: {S_rate: round(S_rate), S_dead: round(S_dead), S_smooth: round(S_smooth),
      blend: round(blend), smoothBasis},
    rate: {operationsWeighted: round(weighted), operations: operations.length, muPerMinute: round(mu), mu0: p.mu0,
      S_rate: round(S_rate)},
    dead: {thresholdSeconds: idle, idleSeconds: round(idleSeconds), share: round(q), q0: p.q0, q1: p.q1, S_dead: round(S_dead)},
    rhythm: {windowSeconds: smoothWidth > 0 ? smoothWidth : null,
      windows: windowed?.bins ?? null, meanPerWindow: round(windowed?.meanPerWindow ?? null),
      cv: round(cv), c0: p.c0, c1: p.c1, S_smooth: round(S_smooth),
      gapCv: round(stats.cv), gaps: stats.n, meanGapSeconds: round(stats.mean), burstiness: round(stats.burstiness)},
    longestGaps: longest,
  };
}

/** The judged seat's native rows inside the scored window, head-trimmed and `before`/`after` merged. */
async function readCommands(file, options) {
  const {team, startMs, endMs, skipHeadSeconds = 0, counted} = options;
  const headMs = startMs + Math.max(0, Number(skipHeadSeconds) * 1000);
  const pairs = new Map();
  const counters = {nativeRows: 0, otherTeam: 0, beforeHead: 0, afterEnd: 0, uncounted: 0, kept: 0};
  const rl = readline.createInterface({input: fs.createReadStream(file), crlfDelay: Infinity});
  for await (const line of rl) {
    if (!line.startsWith('{"kind":"native"')) continue;
    const row = JSON.parse(line);
    counters.nativeRows++;
    const slot = pairs.get(row.nativeId) || {};
    slot[row.phase === 'after' ? 'after' : 'before'] = row;
    pairs.set(row.nativeId, slot);
  }
  const rows = [];
  for (const slot of pairs.values()) {
    const row = mergeRow(slot.before ?? slot.after, slot.after);
    if (row.team !== team) { counters.otherTeam++; continue; }
    if (counted && !counted.has(row.operation)) { counters.uncounted++; continue; }
    if (row.timeMs < headMs) { counters.beforeHead++; continue; }
    if (row.timeMs > endMs) { counters.afterEnd++; continue; }
    counters.kept++;
    rows.push(row);
  }
  rows.sort((a, b) => a.timeMs - b.timeMs || a.nativeId.localeCompare(b.nativeId));
  return {rows, counters};
}

function readJson(file) { return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')); }

/** Scored window: the Stage-3 summary already ends where the match is decided. */
function scoredWindow(matchDir) {
  const summary = path.join(matchDir, 'stage_3', 'summary.json');
  if (fs.existsSync(summary)) {
    const data = readJson(summary);
    return {startMs: 0, endMs: Math.max(0, Number(data.durationMs || 0)), team: Number(data.team),
      endReason: data.endReason ?? null, source: summary};
  }
  const preprocess = path.join(matchDir, 'prepared', 'preprocess.json');
  if (fs.existsSync(preprocess)) {
    const data = readJson(preprocess), window = data.window ?? {};
    return {startMs: Number(window.startMs || 0), endMs: Number(window.endMs || 0),
      team: Number(window.team ?? 0), endReason: null, source: preprocess};
  }
  throw Error(`No stage_3/summary.json or prepared/preprocess.json under ${matchDir}`);
}

async function scoreMatch(matchDir, options = {}) {
  const p = parameters();
  // `extra/native.jsonl` is the clip-safe extract of a faithful replay playback: same command
  // stream, plus the target point / build type the live capture never recorded. A match without it
  // only has the live capture, which cannot tell two orders apart and is scored in degraded mode.
  const extract = path.join(matchDir, 'extra', 'native.jsonl');
  const material = options.telemetry ? 'custom' : fs.existsSync(extract) ? 'native' : 'live';
  const telemetry = options.telemetry
    || (material === 'native' ? extract : path.join(matchDir, 'prepared', 'telemetry.jsonl'));
  if (!fs.existsSync(telemetry)) throw Error(`Missing telemetry: ${telemetry}`);
  const window = scoredWindow(matchDir);
  const team = Number.isFinite(options.team) ? options.team : window.team;
  const suppress = Number.isFinite(options.skipHeadSeconds) ? options.skipHeadSeconds : p.skipHeadSeconds;
  const {rows, counters} = await readCommands(telemetry, {team, startMs: window.startMs, endMs: window.endMs,
    skipHeadSeconds: suppress, counted: countedOperations(p)});
  const {operations, counters: clean} = cleanOperations(rows, p);
  const startMs = window.startMs + Math.max(0, suppress * 1000);
  const score = fluencyScore(operations, {startMs, endMs: window.endMs}, p);
  const warnings = [];
  if (!(window.endMs > window.startMs)) warnings.push('empty_window');
  if (operations.length === 0) warnings.push('no_operations');
  if (operations.length > 0 && score.rhythm.gaps < 2) warnings.push('few_gaps');
  if (window.endReason === 'preprocess_cut') warnings.push('window_cut_at_decision');
  if (clean.degradedCommands > 0) warnings.push('no_coordinates');
  return {
    schema: 1, version: VERSION, appliesToTotal: false,
    match: path.basename(matchDir), team, material,
    source: {telemetry, window: window.source, endReason: window.endReason},
    parameters: {...p},
    counts: {...counters, ...clean},
    window: {startMs: window.startMs, endMs: window.endMs, skipHeadSeconds: suppress,
      headTrimmedMs: suppress * 1000, windowSeconds: round((window.endMs - window.startMs) / 1000),
      activeSeconds: round((window.endMs - startMs) / 1000),
      degraded: clean.degradedCommands > 0 ? 'no_coordinates' : null},
    ...score, operations, warnings,
  };
}

function report(score) {
  const lines = [`Extra fluency ${score.version}  ${score.match}  team ${score.team}  (not in total)`,
    `  fluency        ${score.fluency}`, `  window         ${score.window.startMs}..${score.window.endMs} ms `
      + `(skip head ${score.window.skipHeadSeconds}s, active ${score.window.activeSeconds}s `
      + `of ${score.window.windowSeconds}s)`,
    `  commands       kept ${score.counts.kept}/${score.counts.nativeRows} (other team ${score.counts.otherTeam}, `
      + `head ${score.counts.beforeHead}, tail ${score.counts.afterEnd}, uncounted ${score.counts.uncounted})`,
    `  material       ${score.material === 'native' ? 'replay extract (extra/native.jsonl)'
      : score.material === 'live'
        ? `live capture${score.window.degraded ? ' - no coordinates, degraded' : ''}` : 'custom --telemetry'}`,
    `  operations     ${score.rate.operations} from ${score.counts.unitOrders} unit orders `
      + `(spam ${score.counts.spamDropped}), weighted ${score.rate.operationsWeighted}`,
    `  mu             ${score.rate.muPerMinute}/min (mu0 ${score.rate.mu0}) -> S_rate ${score.components.S_rate}`,
    `  dead           ${score.dead.share} of ${score.window.activeSeconds}s > ${score.dead.thresholdSeconds}s `
      + `-> S_dead ${score.components.S_dead}`,
    `  rhythm         cv ${score.rhythm.cv} over ${score.rhythm.windows ?? '-'} x ${score.rhythm.windowSeconds ?? '-'}s `
      + `(mean ${score.rhythm.meanPerWindow}/win) -> S_smooth ${score.components.S_smooth}`,
    `  gap check      ${score.rhythm.gaps} gaps, mean ${score.rhythm.meanGapSeconds}s, gap cv ${score.rhythm.gapCv}, `
      + `burstiness ${score.rhythm.burstiness}`,
    `  coefficients   ${score.components.smoothBasis}${score.components.S_smooth === 0 ? ' (no rhythm credit)' : ''}`,
    `  longest gaps   ${score.longestGaps.map(g => `${g.gapSeconds}s@${Math.round(g.fromMs / 1000)}s`).join(', ') || '-'}`];
  if (score.warnings.length) lines.push(`  warnings       ${score.warnings.join(', ')}`);
  return lines.join('\n') + '\n';
}

function writeOps(file, operations) {
  const rows = ['t_ms,operation,units,weight,x,y,action,targetId,buildType,applied'];
  for (const op of operations) rows.push([op.t, op.operation, op.units, op.weight, op.x ?? '', op.y ?? '',
    op.action ?? '', op.targetId ?? '', op.buildType ?? '', op.applied].join(','));
  fs.writeFileSync(file, rows.join('\n') + '\n');
}

function matchDirs(root) {
  return fs.readdirSync(root, {withFileTypes: true}).filter(entry => entry.isDirectory()
    && !entry.name.startsWith('_') && entry.name !== 'micro' && entry.name !== 'events-live')
    .map(entry => path.join(root, entry.name))
    .filter(dir => fs.existsSync(path.join(dir, 'prepared', 'telemetry.jsonl')));
}

async function scoreAll(root, options = {}) {
  const rows = [];
  for (const dir of matchDirs(root)) {
    try {
      const score = await scoreMatch(dir, options);
      const out = path.join(dir, 'extra');
      const operations = score.operations;
      // `operations` is omitted from score.json (it can be thousands of rows); ops.csv is the detail.
      delete score.operations;
      fs.mkdirSync(out, {recursive: true});
      fs.writeFileSync(path.join(out, 'score.json'), JSON.stringify(score, null, 2) + '\n');
      fs.writeFileSync(path.join(out, 'score.txt'), report(score));
      writeOps(path.join(out, 'ops.csv'), operations);
      rows.push(score);
    } catch (error) { console.error(`${path.basename(dir)}: ${error.message}`); }
  }
  rows.sort((a, b) => b.fluency - a.fluency);
  const csv = ['match,material,team,fluency,operations,weighted,muPerMinute,deadShare,cv,activeSeconds,warnings'];
  for (const row of rows) csv.push([row.match, row.material, row.team, row.fluency, row.rate.operations,
    row.rate.operationsWeighted, row.rate.muPerMinute, row.dead.share, row.rhythm.cv ?? '',
    row.window.activeSeconds, row.warnings.join('|')].join(','));
  fs.writeFileSync(path.join(root, '_extra-summary.csv'), '\uFEFF' + csv.join('\n') + '\n');
  fs.writeFileSync(path.join(root, '_extra-summary.json'), JSON.stringify(rows.map(row => ({match: row.match,
    material: row.material, team: row.team, fluency: row.fluency, operations: row.rate.operations,
    weighted: row.rate.operationsWeighted, muPerMinute: row.rate.muPerMinute, deadShare: row.dead.share,
    cv: row.rhythm.cv, activeSeconds: row.window.activeSeconds, components: row.components,
    warnings: row.warnings})), null, 1) + '\n');
  return rows;
}

async function main(argv) {
  const args = argv.slice(2), target = args.shift();
  if (!target) throw Error('Usage: node evaluate/score_extra.js <match dir|--all> [--all] [--team N] '
    + '[--telemetry file] [--out dir] [--json]');
  let all = false, team = NaN, telemetry = null, out = null, json = false, skipHeadSeconds = NaN;
  while (args.length) {
    const flag = args.shift();
    const inline = flag.includes('=') ? flag.slice(flag.indexOf('=') + 1) : null;
    const value = inline ?? args.shift();
    if (flag === '--all') { all = true; if (inline != null) args.unshift(value); }
    else if (flag === '--json') { json = true; if (inline != null) args.unshift(value); }
    else if (flag === '--team' || flag.startsWith('--team=')) team = Number(value);
    else if (flag === '--telemetry' || flag.startsWith('--telemetry=')) telemetry = path.resolve(value);
    else if (flag === '--out' || flag.startsWith('--out=')) out = path.resolve(value);
    else if (flag === '--skip-head' || flag.startsWith('--skip-head=')) skipHeadSeconds = Number(value);
    else throw Error(`Unknown option ${flag}`);
  }
  if (all) {
    const rows = await scoreAll(path.resolve(out || target), {team, telemetry, skipHeadSeconds});
    console.log(`scored ${rows.length} matches -> _extra-summary.csv / _extra-summary.json`);
    return rows;
  }
  const dir = path.resolve(target);
  const score = await scoreMatch(dir, {team, telemetry, skipHeadSeconds});
  const operations = score.operations;
  // `operations` is omitted from score.json (it can be thousands of rows); ops.csv is the detail.
  delete score.operations;
  const outDir = path.resolve(out || path.join(dir, 'extra'));
  fs.mkdirSync(outDir, {recursive: true});
  fs.writeFileSync(path.join(outDir, 'score.json'), JSON.stringify(score, null, 2) + '\n');
  fs.writeFileSync(path.join(outDir, 'score.txt'), report(score));
  writeOps(path.join(outDir, 'ops.csv'), operations);
  console.log(json ? JSON.stringify(score, null, 1) : report(score));
  return {outDir, score};
}

if (require.main === module) main(process.argv).catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = {VERSION, PARAMETERS, DEFAULTS, COUNTED, mergeRow, identify, cleanOperations, gapStats, windowCv,
  fluencyScore, readCommands, scoredWindow, scoreMatch, scoreAll, report, main};
