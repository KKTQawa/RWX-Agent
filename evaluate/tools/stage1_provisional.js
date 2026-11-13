#!/usr/bin/env node
'use strict';
/**
 * Stage1 v2-provisional：只重标 f5/f6 的 hi，冻结 W/λ，关闭活跃度闸门。
 *
 *   node evaluate/tools/stage1_provisional.js [--root evaluate/output] [--reps 500]
 *
 * 读当前批的 prepared 命令日志与 telemetry，复算 f1–f6，输出：
 *   - <match>/stage_1_v2_provisional/score.json|score.txt
 *   - _stage1-provisional-summary.json|md、_stage1-provisional-detail.csv
 *
 * 不覆盖 stage_1_v2、score_v2.json、score_v21.json 或 _v21-summary.*。
 */
const fs = require('node:fs');
const path = require('node:path');
const {readLog} = require('../evaluate_stage_1');
const {telemetryEvidence} = require('../score_stage_1_v2');
const base = require('../stage1-v2');
const provisional = require('../stage1-v2-provisional');

const ROOT = path.resolve(__dirname, '..', '..');
const DEFAULT_OUTPUT = path.join(ROOT, 'evaluate', 'output');
const round = (value, digits = 3) => value == null || !Number.isFinite(value)
  ? null : Number(value.toFixed(digits));
const mean = values => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
const median = values => values.length ? base.quantile(values, .5) : null;
const std = values => {
  if (values.length < 2) return null;
  const center = mean(values);
  return Math.sqrt(values.reduce((sum, value) => sum + (value - center) ** 2, 0) / (values.length - 1));
};
const clip = (value, lo, hi) => Math.max(lo, Math.min(hi, value));

function discover(root) {
  const found = [];
  for (const entry of fs.readdirSync(root, {withFileTypes: true})) {
    if (!entry.isDirectory() || entry.name === '_archive' || entry.name === 'micro') continue;
    const dir = path.join(root, entry.name);
    if (fs.existsSync(path.join(dir, 'stage_1_v2', 'score.json'))) found.push(dir);
  }
  return found.sort();
}

function cutMsOf(dir) {
  const evaluation = path.join(dir, 'evaluation_v2.json');
  if (fs.existsSync(evaluation)) {
    const seconds = JSON.parse(fs.readFileSync(evaluation, 'utf8').replace(/^\uFEFF/, '')).scoreWindowSeconds;
    if (Number.isFinite(seconds)) return Math.round(seconds * 1000);
  }
  const stage3 = path.join(dir, 'stage_3', 'score.json');
  if (fs.existsSync(stage3)) {
    const seconds = JSON.parse(fs.readFileSync(stage3, 'utf8')).durationSeconds;
    if (Number.isFinite(seconds)) return Math.round(seconds * 1000);
  }
  return null;
}

function commandsOf(dir) {
  for (const source of [path.join(dir, 'prepared'), dir]) {
    if (!fs.existsSync(source)) continue;
    const name = fs.readdirSync(source).find(file => /^commands-.*\.txt$/i.test(file));
    if (name) return path.join(source, name);
  }
  return null;
}

function telemetryOf(dir) {
  return [path.join(dir, 'prepared', 'telemetry.jsonl'), path.join(dir, 'resim', 'telemetry.jsonl')]
    .find(file => fs.existsSync(file)) || null;
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

function stage3Of(dir) {
  const file = path.join(dir, 'score_v21.json');
  if (!fs.existsSync(file)) return {stage3: null, totalV21: null};
  const score = JSON.parse(fs.readFileSync(file, 'utf8'));
  return {stage3: score.components?.stage3?.value ?? null, totalV21: score.total ?? null};
}

async function loadMatch(dir) {
  const name = path.basename(dir);
  const commandsFile = commandsOf(dir);
  const telemetry = telemetryOf(dir);
  if (!commandsFile || !telemetry) throw Error(`missing commands/telemetry in ${name}`);
  const cutMs = cutMsOf(dir);
  const evidence = await telemetryEvidence(telemetry, cutMs);
  const commands = readLog(commandsFile).commands;
  const raw = base.rawFeatures(commands, evidence.nativeTimes, evidence.durationSeconds);
  const oldScore = base.scoreEvidence(commands, evidence.nativeTimes, evidence.durationSeconds);
  const newScore = provisional.scoreEvidence(commands, evidence.nativeTimes, evidence.durationSeconds);
  const recorded = JSON.parse(fs.readFileSync(path.join(dir, 'stage_1_v2', 'score.json'), 'utf8'));
  const {outcome, label} = outcomeOf(dir);
  const {stage3, totalV21} = stage3Of(dir);
  return {name, dir, commandsFile, telemetry, cutMs, commands, nativeTimes: evidence.nativeTimes,
    durationSeconds: evidence.durationSeconds, raw, oldScore, newScore, recorded, outcome, label, stage3, totalV21,
    recordedDelta: round(oldScore.score - recorded.score)};
}

function report(score) {
  const lines = [`第一阶段 ${score.version}`, '='.repeat(52),
    `总分 ${score.score} / 100（原始 ${score.rawScore}）`];
  for (const [name, group] of Object.entries(score.groups))
    lines.push(`${name.padEnd(9)} 扣 ${String(group.deduction).padStart(7)} / ${group.weight}`);
  lines.push(score.activity.enabled
    ? `活跃度闸门：${score.activity.nativeCommandsPerMinute}/min，得分封顶 ${score.activity.scoreCap}`
    : `活跃度闸门：关闭（记录 ${score.activity.nativeCommandsPerMinute}/min，阈值 ${score.activity.threshold}）`);
  lines.push('状态：provisional-frozen；只在这个 26 局池子里有相对意义，不能与 stage1-v2 混比。');
  return lines.join('\n') + '\n';
}

function writeScore(match) {
  const out = path.join(match.dir, 'stage_1_v2_provisional');
  fs.mkdirSync(out, {recursive: true});
  const payload = {...match.newScore,
    source: {commands: match.commandsFile, telemetry: match.telemetry, cutMs: match.cutMs,
      recordedStage1Score: match.recorded.score},
    comparison: {stage1v2: match.oldScore.score, delta: round(match.newScore.score - match.oldScore.score),
      calibration: provisional.CALIBRATION}};
  fs.writeFileSync(path.join(out, 'score.json'), JSON.stringify(payload, null, 2) + '\n');
  fs.writeFileSync(path.join(out, 'score.txt'), report(payload));
  return out;
}

function rowsOf(matches) {
  return matches.map(match => {
    const values = match.raw.values;
    const oldFeatures = match.oldScore.features, newFeatures = match.newScore.features;
    const totalV21Provisional = Number.isFinite(match.stage3) && Number.isFinite(match.newScore.score)
      ? clip(match.newScore.score * 0.4 + match.stage3 * 0.6, 0, 100) : null;
    return {
      match: match.name, relativePath: path.relative(DEFAULT_OUTPUT, match.dir).replace(/\\/g, '/'),
      outcome: match.outcome, label: match.label,
      durationSeconds: round(match.durationSeconds),
      f1: round(values.f1), f2: round(values.f2), f3: round(values.f3), f4: round(values.f4),
      f5: round(values.f5), f6: round(values.f6),
      f5Tail: round(match.raw.samples.f5.at(-1) ?? null), f6Tail: round(match.raw.samples.f6.at(-1) ?? null),
      f5Samples: match.raw.samples.f5.length, f6Samples: match.raw.samples.f6.length,
      native: match.raw.counts.native,
      nativePerMinute: round(match.newScore.activity.nativeCommandsPerMinute),
      oldScore: match.oldScore.score, newScore: match.newScore.score,
      delta: round(match.newScore.score - match.oldScore.score),
      oldDeduction: match.oldScore.deduction, newDeduction: match.newScore.deduction,
      oldU: Object.fromEntries(['f1', 'f2', 'f3', 'f4', 'f5', 'f6'].map(id => [id, oldFeatures[id].u])),
      newU: Object.fromEntries(['f1', 'f2', 'f3', 'f4', 'f5', 'f6'].map(id => [id, newFeatures[id].u])),
      oldSeverity: Object.fromEntries(['f1', 'f2', 'f3', 'f5', 'f6'].map(id => [id, oldFeatures[id].severity])),
      newSeverity: Object.fromEntries(['f1', 'f2', 'f3', 'f5', 'f6'].map(id => [id, newFeatures[id].severity])),
      oldGate: match.oldScore.activity.applied, newGate: match.newScore.activity.applied,
      recordedScore: match.recorded.score, recordedDelta: match.recordedDelta,
      stage3: match.stage3, totalV21: match.totalV21, totalV21Provisional: round(totalV21Provisional),
      totalDelta: round(totalV21Provisional - match.totalV21),
      startupDeduction: match.newScore.groups.startup.deduction,
      cycleDeduction: match.newScore.groups.cycle.deduction,
      silenceDeduction: match.newScore.groups.silence.deduction,
    };
  });
}

function stats(rows) {
  const scores = rows.map(row => row.newScore), old = rows.map(row => row.oldScore);
  const wins = rows.filter(row => row.outcome === 'win'), losses = rows.filter(row => row.outcome === 'defeat');
  return {
    matches: rows.length,
    old: {mean: round(mean(old)), median: round(median(old)), min: round(Math.min(...old)),
      max: round(Math.max(...old))},
    new: {mean: round(mean(scores)), median: round(median(scores)), min: round(Math.min(...scores)),
      max: round(Math.max(...scores))},
    delta: {mean: round(mean(rows.map(row => row.delta))), min: round(Math.min(...rows.map(row => row.delta))),
      max: round(Math.max(...rows.map(row => row.delta))),
      improved: rows.filter(row => row.delta > 0).length, worsened: rows.filter(row => row.delta < 0).length,
      unchanged: rows.filter(row => row.delta === 0).length},
    outcome: {
      wins: {n: wins.length, oldMean: round(mean(wins.map(row => row.oldScore))),
        newMean: round(mean(wins.map(row => row.newScore))),
        newMedian: round(median(wins.map(row => row.newScore)))},
      losses: {n: losses.length, oldMean: round(mean(losses.map(row => row.oldScore))),
        newMean: round(mean(losses.map(row => row.newScore))),
        newMedian: round(median(losses.map(row => row.newScore)))},
      oldAuc: round(auc(rows.map(row => row.oldScore), rows.map(row => row.outcome === 'win' ? 1 : 0)), 4),
      newAuc: round(auc(rows.map(row => row.newScore), rows.map(row => row.outcome === 'win' ? 1 : 0)), 4),
    },
    totalV21: {currentMean: round(mean(rows.map(row => row.totalV21))),
      provisionalMean: round(mean(rows.map(row => row.totalV21Provisional))),
      deltaMean: round(mean(rows.map(row => row.totalDelta)))},
  };
}

function saturation(rows, key, id) {
  const values = rows.map(row => row[key][id]);
  return {count: values.filter(value => value >= 0.999).length, total: values.length,
    share: round(values.filter(value => value >= 0.999).length / values.length, 4)};
}

function saturationTable(rows) {
  const ids = ['f1', 'f2', 'f3', 'f4', 'f5', 'f6'];
  return ids.map(id => ({id, old: saturation(rows, 'oldU', id), new: saturation(rows, 'newU', id)}));
}

const SCORED_FEATURES = ['f1', 'f2', 'f3', 'f5', 'f6'];
const DIAGNOSTIC_FEATURES = ['f4'];

/** Design acceptance: every *scored* feature must have at most 40% of matches at u=1.
 *  f4 is diagnostic-only and is reported, not failed. */
function saturationCheck(rows, threshold = 0.4) {
  const features = [...SCORED_FEATURES, ...DIAGNOSTIC_FEATURES].map(id => {
    const values = rows.map(row => row.newU[id]).filter(Number.isFinite);
    const count = values.filter(value => value >= 0.999).length;
    const total = values.length;
    const share = total ? count / total : 0;
    const scorer = SCORED_FEATURES.includes(id);
    return {id, scope: scorer ? 'scored' : 'diagnostic', count, total,
      share: round(share, 4), max: round(total ? Math.max(...values) : null),
      p90: round(total ? base.quantile(values, .9) : null), threshold,
      pass: scorer ? share <= threshold + 1e-9 : null,
      matches: rows.filter(row => row.newU[id] >= 0.999).map(row => row.match)};
  });
  const violations = features.filter(feature => feature.scope === 'scored' && !feature.pass)
    .map(feature => feature.id);
  return {threshold, pass: violations.length === 0, violations, features};
}

function featureMedians(rows) {
  const ids = ['f1', 'f2', 'f3', 'f4', 'f5', 'f6'];
  return ids.map(id => ({id, old: round(median(rows.map(row => row.oldU[id]))),
    new: round(median(rows.map(row => row.newU[id])))}));
}

function pearson(xs, ys) {
  const pairs = xs.map((x, i) => [x, ys[i]]).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  if (pairs.length < 2) return null;
  const mx = mean(pairs.map(([x]) => x)), my = mean(pairs.map(([, y]) => y));
  let num = 0, dx = 0, dy = 0;
  for (const [x, y] of pairs) { num += (x - mx) * (y - my); dx += (x - mx) ** 2; dy += (y - my) ** 2; }
  return dx > 0 && dy > 0 ? num / Math.sqrt(dx * dy) : null;
}

function ranks(values) {
  const order = values.map((value, index) => ({value, index})).sort((a, b) => a.value - b.value);
  const result = Array(values.length);
  for (let i = 0; i < order.length;) {
    let j = i;
    while (j + 1 < order.length && order[j + 1].value === order[i].value) j++;
    const rank = (i + j) / 2 + 1;
    for (let k = i; k <= j; k++) result[order[k].index] = rank;
    i = j + 1;
  }
  return result;
}

function spearman(xs, ys) {
  return pearson(ranks(xs), ranks(ys));
}

function auc(scores, labels) {
  let concordant = 0, comparable = 0;
  for (let i = 0; i < scores.length; i++) {
    if (!labels[i]) continue;
    for (let j = 0; j < scores.length; j++) {
      if (labels[j]) continue;
      comparable++;
      if (scores[i] > scores[j]) concordant++;
      else if (scores[i] === scores[j]) concordant += 0.5;
    }
  }
  return comparable ? concordant / comparable : null;
}

function correlationTable(rows) {
  const ids = ['f2', 'f3', 'f5', 'f6'];
  return ids.map(a => ({id: a, values: ids.map(b => ({id: b,
    r: round(pearson(rows.map(row => row.newU[a]), rows.map(row => row.newU[b])), 4)}))}));
}

function external(rows) {
  const stage3 = rows.filter(row => Number.isFinite(row.stage3));
  return {
    stage3N: stage3.length,
    stage1Stage3Pearson: round(pearson(stage3.map(row => row.newScore), stage3.map(row => row.stage3)), 4),
    stage1Stage3Spearman: round(spearman(stage3.map(row => row.newScore), stage3.map(row => row.stage3)), 4),
    oldStage1Stage3Spearman: round(spearman(stage3.map(row => row.oldScore), stage3.map(row => row.stage3)), 4),
    stage1RankChange: round(spearman(rows.map(row => row.oldScore), rows.map(row => row.newScore)), 4),
    totalDeltaMean: round(mean(rows.map(row => row.totalDelta))),
  };
}

// ---------------------------------------------------------------------------
// Perturbations. All operate on the in-memory prepared log; no files are written.

function cloneCommands(commands) {
  return commands.map(command => ({...command}));
}

function largestGap(commands, parameters) {
  const bs = base.clusters(commands.filter(row => row.type === 'A' || row.type === 'B'), parameters.clusterGapSeconds);
  let best = {gap: -1, cut: null};
  for (let index = 0; index < bs.length - 1; index++) {
    const gap = bs[index + 1].start - bs[index].end;
    if (gap > best.gap) best = {gap, cut: bs[index].end + gap / 2};
  }
  return best;
}

function transformedScore(match, commands, nativeTimes, durationSeconds) {
  return provisional.scoreEvidence(commands, nativeTimes, durationSeconds);
}

function perturb(match, family, variant, transformed) {
  const score = transformedScore(match, transformed.commands, transformed.nativeTimes, transformed.durationSeconds);
  if (!score.eligible) return {family, variant, match: match.name, eligible: false};
  return {
    family, variant, match: match.name, eligible: true,
    base: match.newScore.score, score: score.score, delta: round(score.score - match.newScore.score),
    f1Delta: round(score.features.f1.value - match.newScore.features.f1.value),
    f5Delta: round(score.features.f5.value - match.newScore.features.f5.value),
    f6Delta: round(score.features.f6.value - match.newScore.features.f6.value),
    aCount: score.evidence.counts.A, baseACount: match.newScore.evidence.counts.A,
  };
}

function perturbations(match) {
  const out = [];
  const commands = cloneCommands(match.commands);
  const nativeTimes = [...match.nativeTimes];
  const duration = match.durationSeconds;
  const shift = (delta) => {
    const shifted = commands.map(command => ({...command, time: command.time + delta}));
    const shiftedNative = nativeTimes.map(time => time + delta);
    return {commands: shifted, nativeTimes: shiftedNative, durationSeconds: duration + delta};
  };
  const scale = (rho) => ({
    commands: commands.map(command => ({...command, time: command.time * rho})),
    nativeTimes: nativeTimes.map(time => time * rho),
    durationSeconds: duration * rho,
  });
  const insertAt = (delta, cut) => ({
    commands: commands.map(command => command.time >= cut ? {...command, time: command.time + delta} : {...command}),
    nativeTimes: nativeTimes.map(time => time >= cut ? time + delta : time),
    durationSeconds: duration + delta,
  });
  const dropA = (fraction) => {
    const as = commands.map((command, index) => ({command, index})).filter(row => row.command.type === 'A');
    const remove = new Set();
    as.forEach((row, index) => {
      if (fraction === .75) { if (index % 4 !== 0) remove.add(row.index); }
      else {
        const step = fraction === .25 ? 4 : 2;
        if (index % step === step - 1) remove.add(row.index);
      }
    });
    return {commands: commands.filter((_, index) => !remove.has(index)), nativeTimes, durationSeconds: duration};
  };
  const batchify = () => {
    const bs = commands.filter(command => command.type === 'B');
    const as = commands.filter(command => command.type === 'A');
    const start = match.newScore.features.f1.value || 1;
    const bTimes = bs.map((_, index) => start + index * 0.1);
    const aStart = start + Math.max(1, bs.length) * 0.1 + 10;
    const aTimes = as.map((_, index) => Math.min(duration - 0.1, aStart + index * 0.1));
    return {
      commands: [...bs.map((command, index) => ({...command, time: bTimes[index]})),
        ...as.map((command, index) => ({...command, time: aTimes[index]}))],
      nativeTimes: nativeTimes.map((_, index) => start + index * 0.1),
      durationSeconds: duration,
    };
  };

  for (const delta of [5, 15, 30, 60]) out.push(perturb(match, 'P1', `shift+${delta}s`, shift(delta)));
  for (const rho of [1.25, 1.5, 2, 3]) out.push(perturb(match, 'P2', `rho${rho}`, scale(rho)));
  const gap = largestGap(commands, provisional.PARAMETERS);
  const mid = gap.cut ?? duration / 2;
  for (const delta of [15, 30, 60, 120]) {
    out.push(perturb(match, 'P3', `insert${delta}s@mid`, insertAt(delta, mid)));
    out.push(perturb(match, 'P3', `insert${delta}s@end`, insertAt(delta, duration)));
  }
  for (const fraction of [.25, .5, .75]) out.push(perturb(match, 'P4', `dropA${Math.round(fraction * 100)}%`,
    dropA(fraction)));
  out.push(perturb(match, 'P5', 'batchify', batchify()));
  if (gap.cut != null) {
    out.push(perturb(match, 'P6', 'insertA@gap', {
      commands: [...commands, {type: 'A', time: gap.cut, line: 99999, index: commands.length}],
      nativeTimes, durationSeconds: duration,
    }));
  }
  const lastB = base.clusters(commands.filter(row => row.type === 'B'), provisional.PARAMETERS.clusterGapSeconds).at(-1);
  const tailStart = lastB?.end ?? duration * 0.8;
  const spam = [];
  for (let time = tailStart + 5, index = 0; time < duration; time += 5, index++)
    spam.push({type: 'A', time, line: 100000 + index, index: commands.length + index});
  out.push(perturb(match, 'P6', 'spamA@tail', {
    commands: [...commands, ...spam], nativeTimes, durationSeconds: duration,
  }));
  for (const rho of [.5, .25]) out.push(perturb(match, 'R', `rho${rho}`, scale(rho)));
  return out;
}

function passOf(family, delta) {
  if (family === 'P1' || family === 'P2' || family === 'P3' || family === 'P6') return delta <= 0.05;
  if (family === 'P5') return delta <= -1;
  if (family === 'R') return delta >= -0.05;
  return null;
}

function aggregatePerturbations(records) {
  const groups = new Map();
  for (const record of records) {
    if (!record.eligible) continue;
    const key = `${record.family}|${record.variant}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(record);
  }
  return [...groups.entries()].map(([key, rows]) => {
    const [family, variant] = key.split('|');
    const deltas = rows.map(row => row.delta);
    const pass = family === 'P4' ? null : rows.filter(row => passOf(family, row.delta)).length;
    return {family, variant, n: rows.length,
      meanDelta: round(mean(deltas)), minDelta: round(Math.min(...deltas)), maxDelta: round(Math.max(...deltas)),
      meanF5Delta: round(mean(rows.map(row => row.f5Delta))), meanF6Delta: round(mean(rows.map(row => row.f6Delta))),
      pass, fail: pass == null ? null : rows.length - pass};
  }).sort((a, b) => a.family.localeCompare(b.family) || a.variant.localeCompare(b.variant));
}

function seedOf(text) {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index++) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function randomOf(seed) {
  let state = seed >>> 0;
  return () => {
    state ^= state << 13; state >>>= 0;
    state ^= state >>> 17;
    state ^= state << 5; state >>>= 0;
    return state / 4294967296;
  };
}

function blockSample(values, block, random) {
  const output = [];
  while (output.length < values.length) {
    const start = Math.floor(random() * values.length);
    for (let index = 0; index < block && output.length < values.length; index++)
      output.push(values[(start + index) % values.length]);
  }
  return output;
}

function bootstrapSilence(match, reps = 500) {
  const gaps5 = match.raw.samples.f5, gaps6 = match.raw.samples.f6;
  if (gaps5.length < 5 || gaps6.length < 5) return null;
  const [lo5, hi5] = provisional.PARAMETERS.featureThresholdsSeconds.f5;
  const [lo6, hi6] = provisional.PARAMETERS.featureThresholdsSeconds.f6;
  const random = randomOf(seedOf(match.name));
  const startup = match.newScore.groups.startup.deduction;
  const cycle = match.newScore.groups.cycle.deduction;
  const scores = [];
  for (let rep = 0; rep < reps; rep++) {
    const value5 = base.weightedQuantile(blockSample(gaps5, 5, random), provisional.PARAMETERS.weightedQuantile);
    const value6 = base.weightedQuantile(blockSample(gaps6, 5, random), provisional.PARAMETERS.weightedQuantile);
    const u5 = base.normalized(value5, [lo5, hi5]);
    const u6 = base.normalized(value6, [lo6, hi6]);
    scores.push(Math.max(0, 100 - startup - cycle - 40 * (u5 + u6) / 2));
  }
  return {sd: round(std(scores)), mean: round(mean(scores)), p05: round(base.quantile(scores, .05)),
    p95: round(base.quantile(scores, .95))};
}

function bootstrapTable(rows, reps) {
  const values = rows.map(row => ({match: row.match, score: row.newScore, ...bootstrapSilence(row, reps)}))
    .filter(row => row.sd != null);
  const sorted = [...rows].map(row => row.newScore.score).sort((a, b) => a - b);
  const gaps = sorted.slice(1).map((value, index) => value - sorted[index]);
  return {reps, n: values.length, medianSd: round(median(values.map(row => row.sd))),
    maxSd: round(Math.max(...values.map(row => row.sd))),
    medianAdjacentGap: round(median(gaps)),
    ratio: round(median(values.map(row => row.sd)) / median(gaps), 3), rows: values};
}

// ---------------------------------------------------------------------------
// Output.

function table(headers, rows) {
  return [`| ${headers.join(' | ')} |`, `|${headers.map(() => '---').join('|')}|`,
    ...rows.map(row => `| ${row.join(' | ')} |`)].join('\n');
}
const cell = value => String(value ?? '').replace(/\|/g, '\\|');
const num = (value, digits = 3) => Number.isFinite(value) ? Number(value).toFixed(digits) : '—';
const signed = value => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(3)}` : '—';

function markdown(summary) {
  const rows = summary.rows;
  const out = ['# Stage1 v2-provisional 临时标尺', '',
    `生成时间：${summary.generatedAt}`,
    `版本：\`${summary.version}\`；范围：${summary.scope.matches} 局当前批。`,
    '这版只用这批“全为偏差局”的 26 局定标：lo 保留结构下限，hi 取逐局时间加权 P90 的 P90，' +
      'W=(20,40,40) 与 λ=0 冻结，活跃度闸门关闭。**不能与 stage1-v2 的分数混比。**', '',
    '## 1. 标定', '',
    table(['量', '值'], [
      ['f5 hi', num(summary.calibration.f5Hi)],
      ['f6 hi', num(summary.calibration.f6Hi)],
      ['f5 P85 / P95', `${num(summary.calibration.f5P85)} / ${num(summary.calibration.f5P95)}`],
      ['f6 P85 / P95', `${num(summary.calibration.f6P85)} / ${num(summary.calibration.f6P95)}`],
      ['剔除末尾空窗后的 P90（f5 / f6）',
        `${num(summary.calibration.f5HiNoTail)} / ${num(summary.calibration.f6HiNoTail)}`],
      ['f5 饱和（新）', `${summary.saturation.find(row => row.id === 'f5').new.count}/${rows.length}`],
      ['f6 饱和（新）', `${summary.saturation.find(row => row.id === 'f6').new.count}/${rows.length}`],
      ['W / λ', '20/40/40 / 0（冻结）'],
      ['活跃度闸门', '关闭（记录 2/min，不封顶）']]), '',
    '## 2. 逐局原始值与分数', '',
    table(['#', '对局', '窗口s', 'f1', 'f2', 'f3', 'f5', 'f6', 'f5末尾', 'f6末尾', 'S旧', 'S新', 'Δ'],
      rows.map((row, index) => [index + 1, cell(row.match), num(row.durationSeconds, 1), num(row.f1), num(row.f2),
        num(row.f3), num(row.f5), num(row.f6), num(row.f5Tail), num(row.f6Tail), num(row.oldScore),
        num(row.newScore), signed(row.delta)])), '',
    '## 3. 分布与饱和', '',
    table(['指标', '旧 v2', '新 provisional'], [
      ['均值', num(summary.stats.old.mean), num(summary.stats.new.mean)],
      ['中位数', num(summary.stats.old.median), num(summary.stats.new.median)],
      ['最低', num(summary.stats.old.min), num(summary.stats.new.min)],
      ['最高', num(summary.stats.old.max), num(summary.stats.new.max)],
      ['胜局均值', num(summary.stats.outcome.wins.oldMean), num(summary.stats.outcome.wins.newMean)],
      ['败局均值', num(summary.stats.outcome.losses.oldMean), num(summary.stats.outcome.losses.newMean)],
      ['AUC（胜/负）', num(summary.stats.outcome.oldAuc, 4), num(summary.stats.outcome.newAuc, 4)]]), '',
    table(['特征', '旧 u=1', '旧占比', '新 u=1', '新占比', '旧 u 中位', '新 u 中位'],
      summary.saturation.map(row => {
        const oldMedian = summary.featureMedians.find(item => item.id === row.id).old;
        const newMedian = summary.featureMedians.find(item => item.id === row.id).new;
        return [row.id, row.old.count, `${(row.old.share * 100).toFixed(1)}%`, row.new.count,
          `${(row.new.share * 100).toFixed(1)}%`, num(oldMedian), num(newMedian)];
      })), '',
    `### 饱和度验收（阈值 ${(summary.saturationCheck.threshold * 100).toFixed(0)}%）`, '',
    '验收只针对计分特征 f1/f2/f3/f5/f6；f4 仅诊断，不计分，也不参与通过/失败判定。', '',
    table(['特征', '范围', 'u=1', '占比', 'max u', 'P90 u', '判定'],
      summary.saturationCheck.features.map(feature => [feature.id, feature.scope, feature.count,
        `${(feature.share * 100).toFixed(1)}%`, num(feature.max, 3), num(feature.p90, 3),
        feature.pass == null ? '诊断' : (feature.pass ? '通过' : '**超限**')])), '',
    summary.saturationCheck.pass
      ? '**全部计分特征通过**：没有特征超过 40% 饱和。'
      : `**未通过**：${summary.saturationCheck.violations.join('、')} 超过 40%，才需要按 f5/f6 的方法放宽 hi。`, '',
    `新分数相对旧分数：均 ${signed(summary.stats.delta.mean)}，区间 ` +
      `[${signed(summary.stats.delta.min)}, ${signed(summary.stats.delta.max)}]；` +
      `升高 ${summary.stats.delta.improved} 局、降低 ${summary.stats.delta.worsened} 局、` +
      `不变 ${summary.stats.delta.unchanged} 局。`, '',
    '## 4. 特征相关与外部效度', '',
    table(['', ...summary.correlation.map(row => row.id)],
      summary.correlation.map(row => [row.id, ...row.values.map(value => num(value.r, 3))])), '',
    `Stage1 新分与 Stage3 v2.1 的相关：Pearson ${num(summary.external.stage1Stage3Pearson, 4)}、` +
      `Spearman ${num(summary.external.stage1Stage3Spearman, 4)}（n=${summary.external.stage3N}）；` +
      `旧分 Spearman ${num(summary.external.oldStage1Stage3Spearman, 4)}。`,
    `旧/新 Stage1 的 Spearman 排名相关 ${num(summary.external.stage1RankChange, 4)}；` +
      `总分 v2.1 若替换 Stage1，均值变化 ${signed(summary.external.totalDeltaMean)}。`, '',
    '## 5. 扰动检查', '',
    '期望：P1/P2/P3/P6 不让 S 上升；P5（大批+长停顿）必须下降；R（更快）不下降。' +
      'P4 只报告方向。不合格的格子是仍然存在的灵敏度问题，不是通过项。', '',
    table(['族', '档', 'n', 'ΔS 均', 'ΔS 区间', 'Δf5 均', 'Δf6 均', '通过', '失败'],
      summary.perturbation.map(row => [row.family, row.variant, row.n, signed(row.meanDelta),
        `${signed(row.minDelta)}…${signed(row.maxDelta)}`, signed(row.meanF5Delta), signed(row.meanF6Delta),
        row.pass ?? '—', row.fail ?? '—'])), '',
    '## 6. 块自助（只重采样空窗块）', '',
    `对每局 f5/f6 的间隔序列做 5 块自助（${summary.bootstrap.reps} 次），只重算 silence 组；` +
      `S 的块内标准差中位数 ${num(summary.bootstrap.medianSd)}、最大 ${num(summary.bootstrap.maxSd)}，` +
      `相邻局分差中位数 ${num(summary.bootstrap.medianAdjacentGap)}，比值 ${num(summary.bootstrap.ratio)}。` +
      (summary.bootstrap.ratio > 1
        ? ' 标准差大于相邻分差，局间排序不可信。'
        : ' 标准差小于相邻分差，排序在这批内相对可辨。'), '',
    '## 7. 边界', '',
    '- 这批 26 局都偏差，lo 学不出来；f5=5 是 B 簇合并阈值，f6=3 是“一次决策周期 + 一次调用”的结构下限。',
    '- hi=P90 允许最差 3 局饱和；换 P95 会把标尺抬得过高，尤其 f6 会被 235 s 尾部拖走。',
    '- f5/f6 在这批里高度相关，silence 组仍可能重复计罚；W 没有网格搜索，等参考池再定。',
    '- 没有人类局或固定节奏 bot，无法做“人类 u ≤ 0.3”的正对照；绝对刻度仍未校准。',
    '- 这版只在当前 26 局池子里有相对意义，评测期间冻结；新增参考局后必须升版本号。', ''];
  return out.join('\n');
}

function csv(rows) {
  const header = ['match', 'relativePath', 'outcome', 'durationSeconds', 'f1', 'f2', 'f3', 'f4', 'f5', 'f6',
    'f5Tail', 'f6Tail', 'f5Samples', 'f6Samples', 'native', 'nativePerMinute', 'oldScore', 'newScore', 'delta',
    'oldU1', 'newU1', 'oldU2', 'newU2', 'oldU3', 'newU3', 'oldU4', 'newU4', 'oldU5', 'newU5', 'oldU6', 'newU6',
    'oldGate', 'newGate', 'recordedScore', 'recordedDelta', 'stage3',
    'totalV21', 'totalV21Provisional', 'totalDelta'];
  const quote = value => `"${String(value ?? '').replace(/"/g, '""')}"`;
  return [header.join(','), ...rows.map(row => [row.match, row.relativePath, row.outcome, row.durationSeconds,
    row.f1, row.f2, row.f3, row.f4, row.f5, row.f6, row.f5Tail, row.f6Tail, row.f5Samples, row.f6Samples,
    row.native, row.nativePerMinute, row.oldScore, row.newScore, row.delta,
    row.oldU.f1, row.newU.f1, row.oldU.f2, row.newU.f2, row.oldU.f3, row.newU.f3,
    row.oldU.f4, row.newU.f4, row.oldU.f5, row.newU.f5, row.oldU.f6, row.newU.f6,
    row.oldGate, row.newGate, row.recordedScore, row.recordedDelta, row.stage3,
    row.totalV21, row.totalV21Provisional, row.totalDelta].map(quote).join(','))].join('\n') + '\n';
}

async function main(argv = process.argv) {
  const args = argv.slice(2);
  let root = DEFAULT_OUTPUT, reps = 500, threshold = 0.4;
  while (args.length) {
    const flag = args.shift();
    if (flag === '--root') root = path.resolve(args.shift());
    else if (flag === '--reps') reps = Number(args.shift());
    else if (flag === '--threshold') threshold = Number(args.shift());
    else throw Error('Usage: node evaluate/tools/stage1_provisional.js [--root <dir>] [--reps 500] [--threshold 0.4]');
  }
  const matches = [];
  for (const dir of discover(root)) {
    try { matches.push(await loadMatch(dir)); }
    catch (error) { console.error(`SKIP ${path.basename(dir)}: ${error.message}`); }
  }
  for (const match of matches) writeScore(match);
  const rows = rowsOf(matches);
  rows.sort((a, b) => b.newScore - a.newScore || a.match.localeCompare(b.match));
  const perturbation = matches.flatMap(match => perturbations(match));
  const summary = {
    schema: 1, version: provisional.VERSION, generatedAt: new Date().toISOString(),
    scope: {root: path.relative(ROOT, root).replace(/\\/g, '/') || '.', matches: rows.length},
    calibration: {f5Hi: round(base.quantile(matches.map(match => match.raw.values.f5), .9), 6),
      f6Hi: round(base.quantile(matches.map(match => match.raw.values.f6), .9), 6),
      f5P85: round(base.quantile(matches.map(match => match.raw.values.f5), .85), 6),
      f5P95: round(base.quantile(matches.map(match => match.raw.values.f5), .95), 6),
      f6P85: round(base.quantile(matches.map(match => match.raw.values.f6), .85), 6),
      f6P95: round(base.quantile(matches.map(match => match.raw.values.f6), .95), 6),
      f5HiNoTail: round(base.quantile(matches.map(match =>
        base.weightedQuantile(match.raw.samples.f5.slice(0, -1), provisional.PARAMETERS.weightedQuantile)), .9), 6),
      f6HiNoTail: round(base.quantile(matches.map(match =>
        base.weightedQuantile(match.raw.samples.f6.slice(0, -1), provisional.PARAMETERS.weightedQuantile)), .9), 6),
      config: provisional.CALIBRATION},
    stats: stats(rows), saturation: saturationTable(rows), saturationCheck: saturationCheck(rows, threshold),
    featureMedians: featureMedians(rows), correlation: correlationTable(rows), external: external(rows),
    perturbation: aggregatePerturbations(perturbation),
    bootstrap: bootstrapTable(matches, reps),
    rows, perturbations: perturbation,
  };
  fs.writeFileSync(path.join(root, '_stage1-provisional-summary.json'), JSON.stringify(summary, null, 2) + '\n');
  fs.writeFileSync(path.join(root, '_stage1-provisional-summary.md'), markdown(summary) + '\n');
  fs.writeFileSync(path.join(root, '_stage1-provisional-detail.csv'), csv(rows));
  console.log(`Stage1 provisional: ${rows.length} matches, mean ${summary.stats.old.mean} -> ${summary.stats.new.mean}, ` +
    `f5 hi ${summary.calibration.f5Hi}, f6 hi ${summary.calibration.f6Hi}, ` +
    `saturation check ${summary.saturationCheck.pass ? 'PASS' : `FAIL (${summary.saturationCheck.violations.join(',')})`}`);
  return summary;
}

if (require.main === module) main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
module.exports = {discover, loadMatch, rowsOf, stats, saturationTable, saturationCheck,
  SCORED_FEATURES, DIAGNOSTIC_FEATURES, bootstrapSilence, perturbations, aggregatePerturbations, main};
