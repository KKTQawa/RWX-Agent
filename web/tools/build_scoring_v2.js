#!/usr/bin/env node
'use strict';
// Regenerate `web/resource/scoring.json` from the evaluation config.
//
// The page only publishes the standard that is actually in force: Stage1-v2 and Stage3-v2.1.
// The retired v2 / v1 stages are gone from the site (they live in results.json as the comparison
// column), so nobody reads a stale rule table. CASE rules are not here either — they are built
// from each CASE config and its runs in `web/tools/build_micro_results.py`.
const fs = require('node:fs');
const path = require('node:path');
const file = path.resolve(__dirname, '..', 'resource', 'scoring.json');
const {loadConfig, current} = require(path.resolve(__dirname, '..', '..', 'evaluate', 'config.js'));
const config = loadConfig();
const p = current('stage3.parameters', config);
const v21 = current('stage3.v21.parameters', config);
const fundsV3 = p.fundsV3;
const s1 = current('stage1.v2.parameters', config);
const round = value => Number(Number(value).toFixed(3));
const pct = value => `${round(value * 100)}%`;
const pair = value => value.map(round).join('/');
const weights = current('total.v2_1.parameters', config);
const threshold = (id) => pair(s1.featureThresholdsSeconds[id]);

const stage1 = {
  id: 'stage1',
  role: 'current',
  label: '第一阶段 v2',
  version: 'stage1-score-v2',
  title: '交互节奏与持续操作',
  summary: `三组特征各自归一后按权重扣分：启动 ${s1.groupWeights.startup}、回合延迟 ${s1.groupWeights.cycle}、`
    + `空窗 ${s1.groupWeights.silence}。每个特征先按 lo/hi 做 log 归一得到 u，再经 λ=${round(s1.lambda)} 的曲线`
    + `（当前为线性）得到 severity；组内取成员均值，组扣分 = 权重 × 均值。`
    + `底层命令低于 ${round(s1.minimumNativeCommandsPerMinute)} 条/分钟时总分封顶 ${round(s1.activityGateScoreCap)}。`,
  notes: [
    `评分窗口短于 ${round(s1.minimumDurationSeconds)}s 不评分；样本数少于 ${round(s1.minimumSamples)} 时收缩到最差值。`,
    'f4（A→B 决策间隔）只作诊断，不进入扣分。',
    '阈值、λ 与活跃度闸门仍是 provisional：尚未用参考池标定。',
  ],
  items: [
    {name: '启动', cap: s1.groupWeights.startup,
      formula: `f1 = 开局到首个 B 簇的等待时间；lo/hi = ${threshold('f1')}s，log 归一后 u = severity。`,
      description: '衡量开局后多久发出第一条真正生效的行动。'},
    {name: '回合延迟', cap: s1.groupWeights.cycle,
      formula: `f2 = Γ_AB 中位数（lo/hi ${threshold('f2')}s）、f3 = Γ_BA 中位数（lo/hi ${threshold('f3')}s）；`
        + '两项 severity 取均值后乘本组权重。',
      description: '同时约束观察后行动、行动后重新观察。'},
    {name: '空窗', cap: s1.groupWeights.silence,
      formula: `f5 = B 簇空窗、f6 = 底层命令空窗，均取时间加权 P${round(s1.weightedQuantile * 100)}`
        + `（lo/hi ${threshold('f5')}s / ${threshold('f6')}s）；两项 severity 取均值后乘本组权重。`,
      description: '惩罚大批下令后长时间停顿；末尾空窗同样计入。'},
    {name: '活跃度闸门', cap: s1.activityGateScoreCap,
      formula: `底层命令 < ${round(s1.minimumNativeCommandsPerMinute)} 条/分钟时，Stage1 总分封顶 `
        + `${round(s1.activityGateScoreCap)}（不是额外扣分，是上限）。`,
      description: '防止极低操作量仍靠“没有空窗”拿到高分。'},
  ],
};

const stage3v21 = {
  id: 'stage3v21',
  role: 'current',
  label: '第三阶段 v2.1',
  version: 'stage3-score-v2.1-v3',
  title: '严重战场失误与资金利用',
  summary: `stage3-v2.1 = max(0, 100 − 偷袭 v3 − 偷家 v3 − 危险区建造者死亡 − 资金空余 v3)。`
    + `四项上限 ${v21.ambushV3.P_max} / ${v21.barrageV3.P_max} / ${p.grinder.Cap} / ${fundsV3.SingleMax}；`
    + `偷袭/偷家以受袭事件次数为主、伤害只做严重度，资金改用三段释放率。`,
  notes: [
    `偷袭 T_hi=${round(v21.ambushV3.T_hi)}s、R0=${round(v21.ambushV3.R0)}；偷家 T_hi=${round(v21.barrageV3.T_hi)}s、`
      + `R0=${round(v21.barrageV3.R0)}。两个标定值都来自当前 26 局语料，换语料需重跑。`,
    '危险区建造者死亡沿用 v2 规则；资金 v3 的三段切点与权重仍是设计值。',
  ],
  items: [
    {name: '偷袭 v3', cap: v21.ambushV3.P_max,
      formula: `P=${v21.ambushV3.P_max}×(1−e^(−R1/R0))；R1=Σw·u′·sev/(M1+${v21.ambushV3.W_floor})，`
        + `R0=${round(v21.ambushV3.R0)}；准入 ε=${pct(v21.ambushV3.epsilon)}，T0=${v21.ambushV3.T0}s，`
        + `T_hi=${round(v21.ambushV3.T_hi)}s。`,
      description: '我方陆地移动单位被敌方移动单位打后仍空闲的事件；含 T<T0 的快速反应与一击死亡，按价值、延迟与严重度计分。'},
    {name: '偷家 v3', cap: v21.barrageV3.P_max,
      formula: `P=${v21.barrageV3.P_max}×(1−e^(−R2/R0))；R2=Σw·u′·sev/(M2+${v21.barrageV3.W_floor})，`
        + `R0=${round(v21.barrageV3.R0)}；准入 ε=${pct(v21.barrageV3.epsilon)}，T0=${v21.barrageV3.T0}s，`
        + `T_hi=${round(v21.barrageV3.T_hi)}s。`,
      description: '我方建筑遭炮兵缓冲攻击的事件（命中≥2 次或被摧毁）；T 取第一次到最后一发，摧毁取摧毁时刻。'},
    {name: '危险区建造者死亡', cap: p.grinder.Cap,
      formula: `每事件 ${p.grinder.SingleMax}×L×B，全局封顶 ${p.grinder.Cap}。`,
      description: '危险区已存在并过宽限期后，建造类单位仍在其中被击杀。'},
    {name: '资金空余 v3', cap: fundsV3.SingleMax,
      formula: `S=(1−K)^${fundsV3.exponent}×${fundsV3.SingleMax}；K 为三段（切点 ${fundsV3.windowSplits.join('/')}，`
        + `权重 ${fundsV3.windowWeights.join('/')}）加权释放率。`,
      description: '把评分窗口切成三段分别看资金释放率，再按权重合成；触及对局开始/结束的区间不计分。'},
  ],
};

const data = {
  schema: 2,
  updatedAt: new Date().toISOString(),
  fullMatch: {
    stages: [stage1, stage3v21],
    v21: {
      version: stage3v21.version,
      total: 'total-v2.1',
      weights,
      formula: `total-v2.1 = clip(stage1-v2 × ${weights.stage1Weight} + stage3-v2.1 × ${weights.stage3Weight}, `
        + `${weights.clipMin}, ${weights.clipMax})`,
      comparison: 'v2 只作为对照列出现在 results.json，页面上不再单列它的规则表。',
    },
  },
};
fs.writeFileSync(file, JSON.stringify(data, null, 2) + '\n');
console.log(`Updated ${file}: ${data.fullMatch.stages.length} current stages, `
  + `${data.fullMatch.stages.reduce((sum, stage) => sum + stage.items.length, 0)} rule rows`);
