#!/usr/bin/env node
'use strict';
/**
 * v2.1 总分：第三阶段换成「偷袭 v3 + 偷家 v3 + 绞肉机 v2（沿用）+ 资金 v3」，总分改为
 * 直接加权 stage1/stage3：
 *
 *   stage3-v2.1 = max(0, 100 − 偷袭 v3 − 偷家 v3 − 绞肉机 − 资金 v3)
 *   total-v2.1  = clip(stage1-v2 × 0.4 + stage3-v2.1 × 0.6, 0, 100)
 *
 * 只读 `stage_1_v2/score.json`、`stage_3/score.json`、`prepared/telemetry.jsonl` 和
 * `economy.log`；不重跑、不改写 v2 的 `score_v2.json` / `stage_3/score.json`，输出
 * `score_v21.json` / `score_v21.txt`。
 *
 * Usage: node evaluate/score_match_v21.js <match dir> [--economy file] [--cut-ms ms] [--out file]
 */
const fs = require('node:fs');
const path = require('node:path');
const {current, loadConfig, archiveLabelFor} = require('./config');
const {scoreStage3V21} = require('./score_stage_3_v21');
const v2 = require('./score_match_v2');

const CONFIG = loadConfig();
const VERSION = CONFIG.total.v2_1.version;
const STAGE1_WEIGHT = current('total.v2_1.parameters.stage1Weight', CONFIG);
const STAGE3_WEIGHT = current('total.v2_1.parameters.stage3Weight', CONFIG);
const CLIP_MIN = current('total.v2_1.parameters.clipMin', CONFIG);
const CLIP_MAX = current('total.v2_1.parameters.clipMax', CONFIG);
const R0_AMBUSH = current('stage3.v21.parameters.ambushV3.R0', CONFIG);
const R0_BARRAGE = current('stage3.v21.parameters.barrageV3.R0', CONFIG);
const T_HI_AMBUSH = current('stage3.v21.parameters.ambushV3.T_hi', CONFIG);
const T_HI_BARRAGE = current('stage3.v21.parameters.barrageV3.T_hi', CONFIG);
const STAGE1_VERSION = CONFIG.stage1.v2.version;
const STAGE3_VERSION = CONFIG.stage3.version;
const STAGE3_V21_VERSION = CONFIG.stage3.versionV21;
const OUTPUT = path.join(__dirname, 'output');
const round = (value, digits = 3) => Number(value.toFixed(digits));

function read(file) {
  if (!fs.existsSync(file)) throw Error(`Missing score input: ${file}`);
  return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
}

function defaultEconomy(dir) {
  return [path.join(dir, 'prepared', 'economy.log'), path.join(dir, 'resim', 'economy.log'),
    path.join(dir, 'stage_3', 'economy.log')].find(file => fs.existsSync(file)) || null;
}

function combined(stage1, stage3, stage1Weight = STAGE1_WEIGHT, stage3Weight = STAGE3_WEIGHT) {
  return round(Math.max(CLIP_MIN, Math.min(CLIP_MAX,
    stage1 * stage1Weight + stage3 * stage3Weight)));
}

function report(score) {
  const s3 = score.components.stage3, a = s3.ambush, b = s3.barrage, g = s3.grinder;
  const f = s3.funds, replaced = s3.replaced;
  return [`RWX v2.1 总分（${score.version}）`, '='.repeat(52),
    `总分 ${score.total} = Stage1-v2 ${score.components.stage1v2.value} × ${s3.stage1Weight}` +
      ` + Stage3-v2.1 ${s3.value} × ${s3.weight}`,
    `偷袭 v3 扣 ${a.deduction} / ${a.P_max}（事件 ${a.admitted}/${a.events}，M ${a.M}，R1 ${a.R}，R0 ${a.R0}）`,
    `偷家 v3 扣 ${b.deduction} / ${b.P_max}（事件 ${b.admitted}/${b.events}，M ${b.M}，R2 ${b.R}，R0 ${b.R0}）`,
    `绞肉机 扣 ${g.deduction} / ${g.cap}（沿用 v2）`,
    `资金 v2 ${replaced.v2} → v3 ${f.deduction}；资金 K ${f.k}，上限 ${f.singleMax}`,
    `对照 v2 偷袭 ${s3.legacy.ambush.deduction}（r1 ${s3.legacy.ambush.r}）、` +
      `偷家 ${s3.legacy.barrage.deduction}（r2 ${s3.legacy.barrage.r}）`,
    `Stage3-v2 ${s3.baseTotal} → v2.1 ${s3.value}；归档 ${score.archive}；状态 ${score.status}`,
    `对照 total-v2 ${score.comparison.totalV2}（Δ ${score.comparison.delta >= 0 ? '+' : ''}${score.comparison.delta}）`,
    ''].join('\n');
}

async function main(argv) {
  const args = argv.slice(2), target = args.shift();
  if (!target) throw Error('Usage: node evaluate/score_match_v21.js <match dir> [--economy file] [--cut-ms ms] [--out file]');
  let economyFile = null, cutMs = null, out = null, quiet = false;
  while (args.length) {
    const flag = args.shift();
    if (flag === '--economy') economyFile = path.resolve(args.shift());
    else if (flag === '--cut-ms') cutMs = Number(args.shift());
    else if (flag === '--out') out = path.resolve(args.shift());
    else if (flag === '--quiet') quiet = true;
    else throw Error(`Unknown option ${flag}`);
  }
  const dir = path.resolve(target);
  out ||= path.join(dir, 'score_v21.json');
  const stage1 = read(path.join(dir, 'stage_1_v2', 'score.json'));
  const stage3 = read(path.join(dir, 'stage_3', 'score.json'));
  if (stage1.version !== STAGE1_VERSION) throw Error(`Stage1-v2 version ${stage1.version} != ${STAGE1_VERSION}`);
  if (stage3.version !== STAGE3_VERSION) throw Error(`Stage3 version ${stage3.version} != ${STAGE3_VERSION}`);
  if (!stage1.eligible || !Number.isFinite(stage1.score)) throw Error('Stage1-v2 is not eligible');
  if (!stage3.evidenceComplete || !Number.isFinite(stage3.total)) throw Error('Stage3 evidence is incomplete');
  economyFile ||= defaultEconomy(dir);
  if (!economyFile) throw Error('ECONOMY_EVIDENCE_MISSING');
  const s3 = await scoreStage3V21(dir, {economy: economyFile, cutMs});
  if (s3.version !== STAGE3_V21_VERSION) throw Error(`Stage3-v2.1 version ${s3.version} != ${STAGE3_V21_VERSION}`);
  s3.baseVersion = stage3.version;
  s3.baseTotal = stage3.total;
  s3.stage1Weight = STAGE1_WEIGHT;
  s3.weight = STAGE3_WEIGHT;
  const fundsV2 = stage3.breakdown?.find(row => row.family === 'STAGE3_FUNDS');
  s3.replaced = {family: 'STAGE3_FUNDS', v2: fundsV2 ? Number(fundsV2.deduction || 0) : null,
    v3: s3.funds.deduction,
    changed: fundsV2 ? round(Number(fundsV2.deduction || 0) - s3.funds.deduction) : null};
  s3.replacedItems = {
    ambush: {v2: s3.legacy.ambush.deduction, v3: s3.ambush.deduction,
      changed: round(s3.legacy.ambush.deduction - s3.ambush.deduction)},
    barrage: {v2: s3.legacy.barrage.deduction, v3: s3.barrage.deduction,
      changed: round(s3.legacy.barrage.deduction - s3.barrage.deduction)},
  };
  const snapshot = fs.existsSync(path.join(dir, 'score_v2.json')) ? read(path.join(dir, 'score_v2.json')) : null;
  // Archives were published under the retired `stage1×0.4 + stage3×0.6` formula, so the v2 baseline
  // is recomputed with the current v2 formula instead of trusting `score_v2.json`.
  const totalV2 = v2.combined(stage1.score, stage3.total);
  const total = combined(stage1.score, s3.total);
  const score = {schema: 1, version: VERSION,
    archive: archiveLabelFor(path.relative(OUTPUT, dir).replace(/\\/g, '/'), CONFIG),
    weights: {stage1: STAGE1_WEIGHT, stage3: STAGE3_WEIGHT},
    clip: [CLIP_MIN, CLIP_MAX],
    formula: 'stage1v2 * stage1Weight + stage3v2.1 * stage3Weight',
    components: {
      stage1v2: {version: stage1.version, value: stage1.score, weight: STAGE1_WEIGHT,
        source: 'stage_1_v2/score.json'},
      stage3: {version: STAGE3_V21_VERSION, value: s3.total, weight: STAGE3_WEIGHT,
        source: 'prepared/telemetry.jsonl + stage_3/events.jsonl + stage_3/score.json + economy.log', ...s3},
    },
    fundsV3: {...s3.funds, source: economyFile},
    total, comparison: {totalV2, delta: round(total - totalV2),
      items: s3.replacedItems,
      snapshot: snapshot ? {total: snapshot.total, k: snapshot.k ?? null, comparable: false} : null},
    status: 'provisional', provisional: true,
    provisionalReasons: [...new Set([...(stage1.provisionalReasons || []),
      `R0 is calibrated to the baseline median of R1/R2 (${R0_AMBUSH}/${R0_BARRAGE})`,
      `T_hi is the median of the 26 per-match admitted-event T P90 values (${T_HI_AMBUSH}/${T_HI_BARRAGE})`,
      'ambush/barrage v3 count admitted events; fast reactions stay in M and one-shot deaths use the delta floor',
      'funds v3 counts each window opening balance as income and derives 总花费 from the balance identity'])],
  };
  fs.mkdirSync(path.dirname(out), {recursive: true});
  fs.writeFileSync(out, JSON.stringify(score, null, 2) + '\n');
  fs.writeFileSync(path.join(path.dirname(out), 'score_v21.txt'), report(score));
  if (!quiet) console.log(report(score)); return score;
}

if (require.main === module) main(process.argv).catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = {VERSION, STAGE1_WEIGHT, STAGE3_WEIGHT, CLIP_MIN, CLIP_MAX, combined, report, main};
