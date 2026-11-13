#!/usr/bin/env node
'use strict';
/**
 * Stage1 v2-provisional: 26 局全为偏差局时能做的临时标尺。
 *
 * 只有 f5/f6 的 hi 从数据学出来（逐局时间加权 P90 的 P90），lo 保留结构下限；
 * W=(20,40,40) 与 lambda=0 冻结；活跃度闸门关闭（silence 已覆盖低活跃）。
 * 这版只在这个池子里有相对意义，评测期间冻结，不能与 `stage1.v2` 的分数混比。
 */
const {current, loadConfig} = require('./config');
const base = require('./stage1-v2');

const CONFIG = loadConfig();
const BLOCK = CONFIG.stage1.v2_provisional;
if (!BLOCK) throw Error('Missing evaluation config path: stage1.v2_provisional');
const VERSION = BLOCK.version;
const STATUS = BLOCK.status || 'provisional-frozen';
const CALIBRATION = BLOCK.calibration || {};
const PROVISIONAL_REASONS = BLOCK.provisionalReasons || [
  'absolute lo cannot be learned from 26 all-poor matches',
  'hi is the P90 of the 26 per-match time-weighted P90 values',
  'W and lambda are frozen until a reference pool exists',
];
const PARAMETERS = Object.freeze(current('stage1.v2_provisional.parameters', CONFIG));

function scoreEvidence(commands, nativeTimes, durationSeconds, overrides = {}) {
  const merged = {...PARAMETERS, ...overrides,
    groupWeights: {...PARAMETERS.groupWeights, ...(overrides.groupWeights || {})},
    featureThresholdsSeconds: {...PARAMETERS.featureThresholdsSeconds, ...(overrides.featureThresholdsSeconds || {})}};
  return base.scoreEvidence(commands, nativeTimes, durationSeconds, {
    ...merged, version: VERSION, provisional: true, status: STATUS,
    provisionalReasons: PROVISIONAL_REASONS,
  });
}

module.exports = {
  VERSION, STATUS, CALIBRATION, PARAMETERS, PROVISIONAL_REASONS, scoreEvidence,
  rawFeatures: base.rawFeatures, quantile: base.quantile, weightedQuantile: base.weightedQuantile,
  clusters: base.clusters, normalized: base.normalized, curve: base.curve,
};
