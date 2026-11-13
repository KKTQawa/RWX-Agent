#!/usr/bin/env node
'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const {loadConfig, current} = require('../config');

const CONFIG = loadConfig();
const TUNING_POOL = current('policy.tuningPool', CONFIG);
const PARAMS = current('stage3.parameters', CONFIG);
const PARAMS21 = current('stage3.v21.parameters', CONFIG);
const WEIGHTS21 = current('total.v2_1.parameters', CONFIG);

const ROOT = path.resolve(__dirname, '..', '..');
const OUTPUT = path.join(ROOT, 'evaluate', 'output');
const WEB = path.join(ROOT, 'web', 'resource', 'results.json');
const summary = JSON.parse(fs.readFileSync(path.join(OUTPUT, '_v2-summary.json'), 'utf8'));
// v2.1 is the current standard: total-v2.1 = clip(stage1-v2 × 0.4 + stage3-v2.1 × 0.6).
// Its per-match ledger comes from `_v21-summary.json`; v2 stays on the page as the comparison column.
const SUMMARY21 = path.join(OUTPUT, '_v21-summary.json');
const summary21 = fs.existsSync(SUMMARY21) ? JSON.parse(fs.readFileSync(SUMMARY21, 'utf8')) : null;
const read = file => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
const previous = fs.existsSync(WEB) ? read(WEB) : null;
const id = name => crypto.createHash('sha1').update(name).digest('hex').slice(0, 12);
const clock = seconds => `${Math.floor(seconds / 60)}:${String(Math.round(seconds) % 60).padStart(2, '0')}`;

const ARCHIVE = {
  'Ice-Island-(2p)-20261029--20-40_deepseek4.1vsHard_old': {
    date: '2026-10-29 20:40', agents: ['DeepSeek 4.1'],
    title: 'Ice Island (2p) 10-29 20:40 DeepSeek 4.1 vs Hard'},
  'Ice-Island-(2p)-20261030--01-39_dsh1017vsHard_old': {
    date: '2026-10-30 01:39', agents: ['DSH 1.0.17（底层模型未记录）'],
    title: 'Ice Island (2p) 10-30 01:39 DSH 1.0.17 vs Hard'},
  'Ice-Island-(2p)-20261101--18-51_Pi+claudeOpus5.5+dshvsHard_old': {
    date: '2026-11-01 18:51', agents: ['Pi', 'Claude Opus 5.5', 'DSH'],
    title: 'Ice Island (2p) 11-01 18:51 Pi + Claude Opus 5.5 + DSH vs Hard'},
  'Ice-Island-(2p)-20261101--19-16_Pi+deepseek4.1_old': {
    date: '2026-11-01 19:16', agents: ['Pi + DeepSeek 4.1'],
    title: 'Ice Island (2p) 11-01 19:16 Pi + DeepSeek 4.1'},
  'Ice-Island-(2p)-20261101--19-50_Pi=deepseek掺水_old': {
    date: '2026-11-01 19:50', agents: ['Pi + DeepSeek（掺水路由）'],
    title: 'Ice Island (2p) 11-01 19:50 Pi + DeepSeek（掺水路由）'},
  'Ice-Island-(2p)-20261101--21-31_Pi+Kimi3.1provsHard_延迟_old': {
    date: '2026-11-01 21:31', agents: ['Pi + Kimi K3.1 Pro'],
    title: 'Ice Island (2p) 11-01 21:31 Pi + Kimi K3.1 Pro（延迟）'},
  'Ice-Island-(2p)-20261101--21-51_Pi+Kimi3.1provsHard_延迟2_old': {
    date: '2026-11-01 21:51', agents: ['Pi + Kimi K3.1 Pro'],
    title: 'Ice Island (2p) 11-01 21:51 Pi + Kimi K3.1 Pro（延迟2）'},
};

function currentPairs(meta) {
  const tools = meta.tools || {};
  const count = Math.max(1, meta.sessions?.length || 1);
  return (meta.models?.length ? meta.models : [{provider: 'unknown', id: 'unknown', thinking: 'unknown'}]).map(model => ({
    count: meta.models?.length === 1 ? count : 1,
    agent: {provider: model.provider || 'unknown', model: model.id || 'unknown', reasoning: model.thinking || 'unknown'},
    tool: {name: tools.profile || tools.kind || 'unknown', version: tools.version || tools.mcpToolVersion || null,
      extra: tools.detail || null},
  }));
}

function archivePairs(name) {
  return ARCHIVE[name].agents.map(agent => ({count: 1,
    agent: {provider: 'unknown', model: agent, reasoning: 'unknown'},
    tool: {name: 'RWX CLI（历史原始工具）', version: null,
      extra: '历史材料未结构化记录精确工具版本、provider 与推理强度。'}}));
}

function opponent(meta) {
  if (!meta?.map?.teams) return 'AI - Hard';
  const teams = meta.map.teams.filter(row => !/=Player$/.test(row));
  return teams.length ? teams.join(' · ') : 'unknown';
}

const ROWS21 = new Map((summary21?.rows || []).map(row => [row.relativePath, row]));

// v2.1 keeps the v2 fields it reuses (Stage1-v2, 绞肉机) and replaces 偷袭/偷家/资金 with v3,
// so the web ledger can show both the current score and the v2 comparison without recomputing.
function v21Block(row) {
  if (!row) return null;
  const cap = {ambush: PARAMS21.ambushV3.P_max, barrage: PARAMS21.barrageV3.P_max,
    grinder: PARAMS.grinder.Cap, funds: PARAMS.fundsV3.SingleMax};
  const funds = row.funds || {};
  return {
    windowSeconds: row.windowSeconds,
    total: row.totalV21, stage1: row.stage1v2, stage3: row.stage3V3, delta: row.delta,
    items: {
      ambush: {deduction: row.ambush, cap: cap.ambush, events: row.ambushEvents, admitted: row.ambushAdmitted,
        fast: row.ambushFast, saturated: row.ambushSaturated, lowConfidence: row.ambushLowConfidence,
        r: row.ambushR, r0: row.ambushR0, m: row.ambushM, v2: row.ambushV2},
      barrage: {deduction: row.barrage, cap: cap.barrage, events: row.barrageEvents, admitted: row.barrageAdmitted,
        destroyed: row.barrageDestroyed, saturated: row.barrageSaturated, lowConfidence: row.barrageLowConfidence,
        r: row.barrageR, r0: row.barrageR0, m: row.barrageM, v2: row.barrageV2},
      grinder: {deduction: row.grinder, cap: cap.grinder},
      funds: {deduction: row.fundsV3, cap: cap.funds, k: funds.k ?? null, exponent: funds.exponent ?? null,
        windows: (funds.windows || []).map(window => ({k: window.k, seconds: window.seconds,
          income: window.income, available: window.available, spent: window.spent}))},
    },
    v2: {total: row.totalV2, stage3: row.stage3V2, ambush: row.ambushV2, barrage: row.barrageV2},
  };
}

// The v2 page is deliberately a current-batch view. Archives remain reproducible on disk but
// neither enter its ranking nor inflate any v2 counter.
const matches = summary.evaluated.filter(row => row.archive === 'current').map(row => {
  const dir = path.join(OUTPUT, row.relativePath), metaFile = path.join(dir, 'meta.json');
  const meta = fs.existsSync(metaFile) ? read(metaFile) : null, old = ARCHIVE[row.match];
  if (!meta && !old) throw Error(`Missing web metadata for ${row.match}`);
  const stage3 = read(path.join(dir, 'stage_3', 'score.json'));
  const deductions = Object.fromEntries(stage3.breakdown.map(item => [item.family, {
    deduction: item.deduction, cap: item.cap, records: item.items.length,
  }]));
  const result = row.result;
  const legacy = row.optionalLegacy || {};
  const totalV1 = Number.isFinite(legacy.stage1v1) && Number.isFinite(legacy.stage2)
    ? Number((legacy.stage1v1 * .4 + legacy.stage2 * .6).toFixed(3)) : null;
  const v21 = v21Block(ROWS21.get(row.relativePath));
  // The page shows an event count for every deduction cell; grinder keeps the v2 rule, so its
  // record count comes straight from the stage_3 breakdown instead of the v2.1 summary.
  if (v21) v21.items.grinder.events = deductions.STAGE3_GRINDER?.records ?? null;
  return {
    id: id(row.match), archive: row.archive, title: meta?.display_name || old?.title || row.match,
    date: meta?.timing?.startedAt || meta?.date || old?.date || 'unknown',
    map: meta?.map?.name || 'Ice Island (2p)', opponent: meta ? opponent(meta) : 'AI - Hard · x2 收入',
    duration: {scoreSeconds: row.scoreWindowSeconds, gameSeconds: meta?.timing?.gameSeconds ?? null},
    result: {...result, detail: meta?.result?.detail || `${clock(result.atSeconds)} ${result.label}`},
    pairs: meta ? currentPairs(meta) : archivePairs(row.match),
    scores: {totalV2: row.scores.totalV2, stage1V2: row.scores.stage1v2, stage3: row.scores.stage3,
      stage1V1: legacy.stage1v1 ?? null, stage2: legacy.stage2 ?? null, totalV1},
    stage3: {version: stage3.version, deductions},
    v21,
    evidenceSource: row.evidenceSource,
    evaluation: meta?.evaluation || null,
    notes: meta?.notes || ['历史材料已用忠实 resim 还原；未记录的模型/工具字段保持 unknown。'],
  };
}).sort((a, b) => (b.v21?.total ?? b.scores.totalV2) - (a.v21?.total ?? a.scores.totalV2));

const totals = matches.map(match => match.scores.totalV2);
const totals21 = matches.map(match => match.v21?.total).filter(value => Number.isFinite(value));
const deltas = matches.map(match => match.v21?.delta).filter(value => Number.isFinite(value));
const round3 = value => Number(value.toFixed(3));
const mean = list => list.length ? round3(list.reduce((a, b) => a + b, 0) / list.length) : null;
const median = list => {
  if (!list.length) return null;
  const sorted = [...list].sort((a, b) => a - b), middle = Math.floor(sorted.length / 2);
  return round3(sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2);
};
const bestV2 = [...matches].sort((a, b) => b.scores.totalV2 - a.scores.totalV2)[0];
const best21 = matches[0];
const IGNORED_REASON = {
  replay_desync: '重放与录制分叉（校验不一致条数见原因后缀），材料只能算出一部分，不猜分',
  commands_or_economy_missing: '缺少命令日志或经济日志，无法建立评分窗口',
  stage3_evidence_unavailable: '没有第三阶段证据，且无法用回放补齐',
};
const ignored = summary.ignored.map(row => {
  const key = Object.keys(IGNORED_REASON).find(name => row.reason.startsWith(name)) || null;
  return {title: row.match, relativePath: row.relativePath, reason: row.reason,
    note: key ? IGNORED_REASON[key] : '材料不满足评估门槛'};
});
const currentIgnored = ignored.filter(item => item.relativePath.split('/')[0] !== '_archive');

// v1 is a frozen snapshot: preserve both its ledger rows and rules when regenerating v2.
const V1 = {
  version: 'total-v1',
  formula: 'stage1-v1 × 0.4 + stage2 × 0.6',
  weights: {stage1: .4, stage2: .6},
  frozen: true, frozenAt: '2026-11-06',
  note: 'v1 已冻结：2026-11-06 之后只维护 v2。这里只保留旧材料能复算出的分数，缺任一阶段就留空；'
    + '不计均分、不进排名，也不再作为调参依据。',
  counts: {scored: matches.filter(match => match.scores.totalV1 != null).length,
    missing: matches.filter(match => match.scores.totalV1 == null).length},
  stage1: {label: '第一阶段 v1', caps: [15, 5, 5, 8, 18, 10, 8, 15, 8, 8, 6, 10],
    names: ['首个行动指令', '首个采矿建造', '首个建造者生产', 'A→B 周期去离群均值',
      'B→A 等待去离群均值', 'B→A 等待离群值', 'A→B 决策离群值', '相邻底层命令间隔',
      'A→A 离群占比', 'B→B 离群占比', '底层生产指令 / 分钟', 'A/B 比值']},
  stage2: {label: '第二阶段 v2', caps: current('stage2.v2.parameters.caps', CONFIG)},
};
if (previous?.v1?.frozen) Object.assign(V1, previous.v1);
V1.matches = previous?.v1?.matches || previous?.matches || [];
const results = {
  schema: 3, generatedAt: new Date().toISOString(), archives: summary.archives,
  standard: {version: 'total-v2', formula: 'stage1-v2 − (100 − stage3) × (1−k)',
    k: current('total.v2.parameters.k', CONFIG),
    stage1: 'stage1-score-v2', stage3: 'stage3-score-v2', provisional: true,
    tuningPool: summary.tuningPool, role: 'comparison'},
  standard21: summary21 ? {
    version: 'total-v2.1',
    formula: `total-v2.1 = clip(stage1-v2 × ${WEIGHTS21.stage1Weight} + stage3-v2.1 × ${WEIGHTS21.stage3Weight}, ${WEIGHTS21.clipMin}, ${WEIGHTS21.clipMax})`,
    detailFormula: summary21.formula,
    weights: {stage1: WEIGHTS21.stage1Weight, stage3: WEIGHTS21.stage3Weight},
    clip: [WEIGHTS21.clipMin, WEIGHTS21.clipMax],
    stage1: 'stage1-score-v2', stage3: summary21.stage3Version,
    caps: {ambush: PARAMS21.ambushV3.P_max, barrage: PARAMS21.barrageV3.P_max,
      grinder: PARAMS.grinder.Cap, funds: PARAMS.fundsV3.SingleMax},
    calibration: summary21.calibration,
    stats: summary21.stats?.current || null,
    comparison: {version: 'total-v2', stage3: 'stage3-score-v2',
      note: 'v2 是上一版口径，只作对照：偷袭/偷家仍按伤害占比计，Stage3 常被压到 0，总分普遍偏低。'},
    note: 'v2.1 是当前口径：total-v2.1 = clip(stage1-v2 × 0.4 + stage3-v2.1 × 0.6, 0, 100)；'
      + 'stage3-v2.1 = max(0, 100 − 偷袭v3 − 偷家v3 − 绞肉机v2 − 资金v3)。',
  } : null,
  v1: V1,
  overview: {matches: matches.length, wins: matches.filter(match => match.result.outcome === 'win').length,
    defeats: matches.filter(match => match.result.outcome === 'defeat').length,
    ignored: currentIgnored.length,
    archives: {},
    average: Number((totals.reduce((a, b) => a + b, 0) / totals.length).toFixed(3)),
    best: {id: bestV2.id, title: bestV2.title, totalV2: bestV2.scores.totalV2}},
  overview21: {matches: totals21.length,
    average: mean(totals21), median: median(totals21),
    min: totals21.length ? round3(Math.min(...totals21)) : null,
    max: totals21.length ? round3(Math.max(...totals21)) : null,
    positive: totals21.filter(value => value > 0).length,
    averageDelta: mean(deltas),
    improved: deltas.filter(value => value > 0).length,
    best: {id: best21.id, title: best21.title, totalV21: best21.v21?.total ?? null}},
  matches, ignored: currentIgnored,
  method: {
    sources: ['stage_1_v2/score.json', 'stage_3/score.json（含资金 v2）', 'score_v21.json（v2.1 明细）',
      '_v21-summary.json（26 局 v2.1 汇总）', 'score_v2.json', 'meta.json / evaluation_v2.json',
      '忠实 resim 的 playback.json 校验', 'evaluate/config.json 参数快照'],
    limits: ['Stage1-v2 的阈值、lambda 与活跃度闸门仍为 provisional；v2.1 沿用同一份 Stage1 分数。',
      'v2.1 的偷袭/偷家改用 v3（以受袭事件次数为主、伤害只做严重度），资金改用 v3 三段 K；绞肉机仍是 v2。'
        + 'v2 的伤害占比版保留为对照列，不参与 v2.1 排名。',
      `当前参数（偷袭 P_max=${PARAMS21.ambushV3.P_max}、偷家 P_max=${PARAMS21.barrageV3.P_max}、`
        + `绞肉机 Cap=${PARAMS.grinder.Cap}、资金 Cap=${PARAMS.fundsV3.SingleMax}）下 `
        + `${totals21.filter(value => value === 0).length}/${totals21.length} 局的 total-v2.1 为 0。`,
      'v3 的 T_hi（偷袭 21.122s / 偷家 23.152s）取 26 局逐局准入事件 T 的 P90 中位数，R0 取 26 局 R 的中位数；'
        + '换语料后这两个标定值需要重跑，页面不会自动更新。',
      '资金 v3 的三段切点与权重（0.25/0.75、0.4/0.4/0.2）仍是设计值；触及对局开始/结束的资金区间不计分。',
      '4P 归档局重放会分叉、1 局回放未完成，均只记录材料、不进入本表；胜负不进入公式。'],
  },
};
fs.writeFileSync(WEB, JSON.stringify(results, null, 2) + '\n');
console.log(`Wrote ${WEB}: ${matches.length} current matches, ${results.overview.wins} win, ` +
  `${results.overview.defeats} defeats, ${ignored.length} ignored`);
