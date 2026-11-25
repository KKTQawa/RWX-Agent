const $ = (selector, root = document) => root.querySelector(selector);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[character]);

// Every deduction below belongs to stage3-score-v2.1-v3; labels come from scoring.json.
const DEDUCTIONS = [
  {key: "ambush", attr: "AMBUSH", label: "偷袭 v3"},
  {key: "barrage", attr: "BARRAGE", label: "偷家 v3"},
  {key: "grinder", attr: "GRINDER", label: "危险区建造者死亡"},
  {key: "funds", attr: "FUNDS", label: "资金空余 v3"},
];
const OUTCOME_NAMES = {win: "胜利", defeat: "战败", draw: "平局", unknown: "未知"};
const EVIDENCE_NAMES = {live: "实时遥测", "faithful-resim": "忠实回放重演"};

// 操作流畅度四元组（extra-fluency-v1，附加分，不计入 total）：流畅度 / μ / q / CV。
// `material` 决定 μ 与 CV 能不能跨局比较：native = 回放重采带坐标，live = 旧采集降级。
const FLUENCY_MATERIAL = {native: "原生", live: "降级"};
const FLUENCY_HELP = "操作流畅度四元组：流畅度 / μ 加权操作每分钟 / q 大于 8 秒发呆占比 / CV 30 秒窗口操作数变异系数；附加分，不计入 total，不参与排名。";

// A dash is not data. Every formatter below either returns a real value or says what is missing.
const score = (value, digits = 1) => typeof value === "number" ? value.toFixed(digits) : "未记录";
const signed = (value, digits = 1) => typeof value === "number" ? `${value > 0 ? "+" : ""}${value.toFixed(digits)}` : "未记录";
const duration = (seconds, fallback = "未记录") => {
  if (typeof seconds !== "number") return fallback;
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
};
const dateLabel = (value) => {
  if (!value) return "日期未记录";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : new Intl.DateTimeFormat("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false}).format(parsed);
};
const evidenceLabel = (value) => EVIDENCE_NAMES[value] || value || "评分材料已归档";
const outcomeLabel = (value) => OUTCOME_NAMES[value] || "未知";
const scoreTier = (value) => value >= 60 ? "high" : value >= 30 ? "mid" : "low";
const fixed = (value, digits = 1) => typeof value === "number" ? value.toFixed(digits) : "未记录";
const cvText = (value) => typeof value === "number" ? value.toFixed(2) : "窗不足";
const fluencyMaterial = (value) => FLUENCY_MATERIAL[value] || "材料未知";
const fluencyTuple = (fluency) => `μ ${fixed(fluency.mu)} · q ${fixed(fluency.dead, 2)} · CV ${cvText(fluency.cv)}`;
const total21 = (match) => match.v21?.total ?? null;
const stage3Rule = () => scoringData.fullMatch.stages.find((stage) => stage.id === "stage3v21");

let ledgerData;
let scoringData;
let microData;
let matchIds;
const openMatches = new Set();

// Stable per-match code (M01, M02, …) from resource/match-ids.json. Archived matches have none.
function matchCode(match) {
  return matchIds?.matches?.[match.id] || "";
}

function pairText(pairs = []) {
  return pairs.map((pair) => {
    const count = pair.count > 1 ? ` ×${pair.count}` : "";
    return `${pair.agent?.model || "模型未记录"}${count} × ${pair.tool?.name || "工具未记录"}`;
  }).join(" / ") || "未记录模型与工具";
}

function searchablePairText(pairs = []) {
  return pairs.flatMap((pair) => [pair.agent?.model, pair.agent?.provider, pair.agent?.reasoning, pair.tool?.name, pair.tool?.version, pair.tool?.extra]).filter(Boolean).join(" ");
}

// Second line of a deduction cell: the real count behind the number, never a placeholder.
function deductionNote(key, item = {}) {
  if (key === "ambush" || key === "barrage") {
    const events = item.events ?? 0;
    return `${item.admitted ?? 0}/${events} 条准入`;
  }
  if (key === "grinder") return `${item.events ?? 0} 次死亡`;
  if (key === "funds") return Array.isArray(item.windows) && item.windows.length ? `${item.windows.length} 段窗口` : "无资金窗口";
  return `上限 ${score(item.cap, 0)}`;
}

function deductionCell(key, item = {}) {
  const actual = item.deduction ?? 0;
  return `<strong class="deduction-value${actual > 0 ? " has-deduction" : ""}">−${score(actual)} <span>/ ${score(item.cap, 0)}</span></strong><small>${esc(deductionNote(key, item))}</small>`;
}

// 资金 v2 是上一版口径的资金空余扣分（Stage3 v2 的 STAGE3_FUNDS），列里只给分数。
function fundsV2Cell(match) {
  const item = match.stage3?.deductions?.STAGE3_FUNDS || {};
  const deduction = item.deduction ?? 0;
  return `<strong class="deduction-value${deduction > 0 ? " has-deduction" : ""}">−${score(deduction)} <span>/ ${score(item.cap, 0)}</span></strong>`;
}

// 四元组只在完整对局里出现：流畅度本身不计入 total，只作为诊断信息随行显示。
function fluencyCell(fluency) {
  if (!fluency) return `<span class="fluency-missing">未评估</span>`;
  return `<strong class="fluency-value ${scoreTier(fluency.score)}">${score(fluency.score)}</strong><small class="fluency-tuple">${esc(fluencyTuple(fluency))}</small><small class="fluency-note">${esc(fluencyMaterial(fluency.material))}材料 · 附加分</small>`;
}

function evidenceCell(key, item = {}) {
  if (key === "ambush" || key === "barrage") {
    const bits = [`准入 ${item.admitted ?? 0}/${item.events ?? 0}`];
    if (item.saturated) bits.push(`饱和 ${item.saturated}`);
    if (item.destroyed) bits.push(`摧毁 ${item.destroyed}`);
    if (typeof item.r === "number") bits.push(`R ${item.r.toFixed(3)} / R0 ${score(item.r0, 3)}`);
    if (item.lowConfidence) bits.push("低置信");
    return bits.join(" · ");
  }
  if (key === "grinder") {
    const events = item.events ?? 0;
    return events ? `${events} 次建造者死亡 · 每事件 8×L×B` : "没有建造者在危险区阵亡";
  }
  if (key === "funds") {
    const bits = [];
    if (typeof item.k === "number") bits.push(`K ${item.k.toFixed(3)}`);
    if (typeof item.exponent === "number") bits.push(`指数 ${item.exponent}`);
    if (Array.isArray(item.windows) && item.windows.length) bits.push(`${item.windows.length} 段窗口`);
    return bits.join(" · ") || "评分窗口内没有资金区间";
  }
  return `上限 ${score(item.cap, 0)}`;
}

function renderPairsTable(pairs = []) {
  if (!pairs.length) return "<p>本局未记录模型与工具信息。</p>";
  return `<div class="detail-table-scroll"><table class="nested-table"><thead><tr><th>数量</th><th>模型</th><th>Provider</th><th>推理强度</th><th>工具</th><th>版本 / 改造</th></tr></thead><tbody>${pairs.map((pair) => `<tr><td>${esc(pair.count || 1)}</td><td><b>${esc(pair.agent?.model || "未记录")}</b></td><td>${esc(pair.agent?.provider || "未记录")}</td><td>${esc(pair.agent?.reasoning || "未记录")}</td><td>${esc(pair.tool?.name || "未记录")}</td><td>${esc([pair.tool?.version, pair.tool?.extra].filter(Boolean).join(" · ") || "未记录")}</td></tr>`).join("")}</tbody></table></div>`;
}

function comparisonTable(match) {
  const v21 = match.v21;
  if (!v21) return "";
  const rows = [
    ["total-v2.1 / v2", v21.total, v21.v2?.total, v21.delta, false],
    ["Stage3", v21.stage3, v21.v2?.stage3, (v21.stage3 ?? 0) - (v21.v2?.stage3 ?? 0), false],
    ["偷袭（扣分）", v21.items?.ambush?.deduction, v21.v2?.ambush, (v21.items?.ambush?.deduction ?? 0) - (v21.v2?.ambush ?? 0), true],
    ["偷家（扣分）", v21.items?.barrage?.deduction, v21.v2?.barrage, (v21.items?.barrage?.deduction ?? 0) - (v21.v2?.barrage ?? 0), true],
  ];
  return `<section class="detail-compare"><h3>v2.1 与 v2 对照</h3><div class="detail-table-scroll"><table class="nested-table compare-table"><thead><tr><th>指标</th><th>v2.1（当前）</th><th>v2（对照）</th><th>Δ</th></tr></thead><tbody>${rows.map(([name, current, previous, delta, lowerIsBetter]) => {
    const better = lowerIsBetter ? delta < 0 : delta > 0;
    const worse = lowerIsBetter ? delta > 0 : delta < 0;
    return `<tr><th scope="row">${esc(name)}</th><td><b>${score(current)}</b></td><td>${score(previous)}</td><td class="${better ? "positive-number" : worse ? "negative-number" : ""}">${signed(delta)}</td></tr>`;
  }).join("")}</tbody></table></div><p class="compare-note">绿色表示 v2.1 更好：总分与 Stage3 越高越好，偷袭 / 偷家扣分越低越好。</p></section>`;
}

function renderMatchDetail(match, detailId) {
  const rules = stage3Rule()?.items || [];
  const v21 = match.v21 || {};
  const notes = [match.result?.detail, ...(match.notes || []), match.evaluation?.reason].filter(Boolean);
  const rows = DEDUCTIONS.map(({key, label}, index) => {
    const item = v21.items?.[key] || {};
    const rule = rules[index] || {};
    return `<tr><th scope="row">${esc(rule.name || label)}<small>${esc(key.toUpperCase())}</small></th><td><b class="negative-number">−${score(item.deduction)}</b></td><td>${score(item.cap, 0)}</td><td>${esc(evidenceCell(key, item))}</td><td><code>${esc(rule.formula || "规则未记录")}</code></td><td>${esc(rule.description || "说明未记录")}</td></tr>`;
  }).join("");
  const gameSeconds = match.duration?.gameSeconds;
  const fluency = match.fluency;
  const fluencyFact = fluency
    ? `<div><dt>操作流畅度</dt><dd>${score(fluency.score)} · ${esc(fluencyTuple(fluency))}（${esc(fluencyMaterial(fluency.material))}材料${fluency.appliesToTotal ? "" : "，附加分"}）</dd></div>`
    : "";
  return `<tr class="match-detail-row" id="${esc(detailId)}"${openMatches.has(match.id) ? "" : " hidden"}><td colspan="15"><div class="match-detail-panel">
    <section class="match-facts"><h3>对局与材料</h3><dl>
      <div><dt>编号</dt><dd>${esc(matchCode(match) || "未分配")}</dd></div>
      <div><dt>完整标题</dt><dd>${esc(match.title)}</dd></div><div><dt>地图</dt><dd>${esc(match.map || "未记录")}</dd></div>
      <div><dt>对手 / 规则</dt><dd>${esc(match.opponent || "未记录")}</dd></div><div><dt>结局</dt><dd>${esc(outcomeLabel(match.result?.outcome))}${match.result?.atSeconds != null ? ` · ${duration(match.result.atSeconds)}` : ""}</dd></div>
      <div><dt>评分窗口</dt><dd>${duration(v21.windowSeconds ?? match.duration?.scoreSeconds)}</dd></div><div><dt>游戏时长</dt><dd>${duration(gameSeconds, "材料只记录了评分窗口")}</dd></div>
      <div><dt>证据来源</dt><dd>${esc(evidenceLabel(match.evidenceSource))}</dd></div><div><dt>评分版本</dt><dd>${esc(ledgerData.standard21?.stage3 || "stage3-score-v2.1-v3")}</dd></div>
      ${fluencyFact}
    </dl></section>
    <section><h3>Agent 与工具</h3>${renderPairsTable(match.pairs)}</section>
    ${comparisonTable(match)}
    <section class="detail-deductions"><h3>Stage3-v2.1 逐项扣分与公式</h3><div class="detail-table-scroll"><table class="nested-table deduction-detail-table"><thead><tr><th>扣分项</th><th>实扣</th><th>上限</th><th>证据</th><th>公式</th><th>判定说明</th></tr></thead><tbody>${rows}</tbody></table></div></section>
    ${notes.length ? `<aside class="material-notes"><h3>材料说明</h3>${notes.map((note) => `<p>${esc(note)}</p>`).join("")}</aside>` : ""}
  </div></td></tr>`;
}

function filteredMatches() {
  const query = $("#match-search").value.trim().toLocaleLowerCase("zh-CN");
  const outcome = $("#outcome-filter").value;
  const sort = $("#sort-matches").value;
  const rows = ledgerData.matches.filter((match) => {
    if (outcome !== "all" && match.result?.outcome !== outcome) return false;
    if (!query) return true;
    const haystack = [match.title, match.map, match.opponent, searchablePairText(match.pairs)].filter(Boolean).join(" ").toLocaleLowerCase("zh-CN");
    return haystack.includes(query);
  });
  const deduction = (match) => 100 - (match.v21?.stage3 ?? 100);
  rows.sort((a, b) => {
    if (sort === "score-asc") return (total21(a) ?? 0) - (total21(b) ?? 0);
    if (sort === "date-desc") return new Date(b.date) - new Date(a.date);
    if (sort === "date-asc") return new Date(a.date) - new Date(b.date);
    if (sort === "deduction-desc") return deduction(b) - deduction(a);
    return (total21(b) ?? 0) - (total21(a) ?? 0);
  });
  return rows;
}

function renderMatchTable() {
  const matches = filteredMatches();
  $("#match-filter-status").textContent = `显示 ${matches.length} / ${ledgerData.matches.length} 场`;
  $("#match-table-body").innerHTML = matches.map((match, index) => {
    const result = match.result || {};
    const detailId = `match-detail-${match.id}`;
    const v21 = match.v21 || {};
    const items = v21.items || {};
    const expanded = openMatches.has(match.id);
    // Second line of the duration cell always carries real information: the game length when the
    // materials recorded it, otherwise where the numbers came from.
    const gameNote = typeof match.duration?.gameSeconds === "number"
      ? `游戏 ${duration(match.duration.gameSeconds)}`
      : evidenceLabel(match.evidenceSource);
    return `<tr class="match-row">
      <td class="expand-cell"><button class="match-expand" type="button" data-match-id="${esc(match.id)}" aria-expanded="${expanded}" aria-controls="${esc(detailId)}" aria-label="${expanded ? "收起" : "展开"}${esc(match.title)}的扣分详情"><span aria-hidden="true"></span></button></td>
      <th scope="row" class="match-name-cell"><span class="row-index">${esc(matchCode(match) || String(index + 1).padStart(2, "0"))}</span><div><b>${esc(match.title)}</b>${match.scriptAi ? `<span class="row-tag">脚本基线 · fast:8</span>` : ""}<small>${esc(dateLabel(match.date))}</small></div></th>
      <td class="pair-cell"><b>${esc(pairText(match.pairs))}</b>${match.pairs?.some((pair) => pair.tool?.extra) ? `<small>${esc(match.pairs.map((pair) => pair.tool?.extra).filter(Boolean).join(" / "))}</small>` : ""}</td>
      <td class="map-cell"><b>${esc(match.map || "未记录")}</b><small>${esc(match.opponent || "未记录")}</small></td>
      <td><span class="result-badge ${esc(result.outcome || "unknown")}">${esc(outcomeLabel(result.outcome))}</span><small class="cell-note">${result.atSeconds != null ? duration(result.atSeconds) : "时长未记录"}</small></td>
      <td class="score-cell"><strong class="total-score ${scoreTier(v21.total)}">${score(v21.total)}</strong><small>/ 100</small></td>
      <td class="stage-score"><strong>${score(v21.stage1)}</strong><small>/ 100</small></td>
      <td class="stage-score"><strong>${score(v21.stage3)}</strong><small>/ 100</small></td>
      ${DEDUCTIONS.map(({key}) => `<td class="deduction-cell">${deductionCell(key, items[key])}</td>`).join("")}
      <td class="deduction-cell funds-v2-cell">${fundsV2Cell(match)}</td>
      <td class="fluency-cell" title="${esc(FLUENCY_HELP)}">${fluencyCell(match.fluency)}</td>
      <td class="duration-cell"><b>${duration(v21.windowSeconds ?? match.duration?.scoreSeconds)}</b><small>${esc(gameNote)}</small></td>
    </tr>${renderMatchDetail(match, detailId)}`;
  }).join("") || `<tr><td colspan="15" class="empty-state">没有符合当前筛选条件的对局。</td></tr>`;
}

function renderKpis() {
  const overview = ledgerData.overview || {};
  const v21 = ledgerData.overview21 || {};
  const best = v21.best?.title || "未记录";
  const items = [
    [v21.matches ?? overview.matches, "当前对局", `${overview.wins} 胜 / ${overview.defeats} 负`],
    [score(v21.average), "平均 total-v2.1", `中位 ${score(v21.median)}`],
    [score(v21.max), "最高 total-v2.1", best],
    [signed(v21.averageDelta), "相对 v2 平均提升", `${v21.improved ?? 0}/${v21.matches ?? 0} 局上升`],
  ];
  $("#results-kpis").innerHTML = items.map(([value, label, note]) => `<div><span>${esc(label)}</span><b>${esc(value)}</b><small>${esc(note)}</small></div>`).join("");
  $("#last-updated").textContent = ledgerData.generatedAt ? new Intl.DateTimeFormat("zh-CN", {dateStyle: "medium", timeStyle: "short"}).format(new Date(ledgerData.generatedAt)) : "未记录";
  $("#total-formula").textContent = ledgerData.standard21?.formula || "total-v2.1 = clip(stage1-v2 × 0.4 + stage3-v2.1 × 0.6, 0, 100)";
  $("#formula-k").textContent = `v2 平均 ${score(overview.average)} 作对照`;
}

// Only the two stages that actually score today: Stage1-v2 and Stage3-v2.1.
function renderRuleTables() {
  $("#full-rule-tables").innerHTML = scoringData.fullMatch.stages.map((stage) => `
    <article class="rule-group" id="rules-${esc(stage.id)}">
      <header>
        <div><span>${esc(stage.label)}</span><h3>${esc(stage.title)}</h3></div>
        <b class="rule-role">当前计分</b>
        <p>${esc(stage.summary)}</p>
        <small>${esc(stage.version)}</small>
      </header>
      <div class="table-scroll" tabindex="0" aria-label="${esc(stage.title)}规则表，可横向滚动">
        <table class="data-table rule-table">
          <thead><tr><th>#</th><th>扣分项</th><th>上限</th><th>公式 / 阈值</th><th>判定说明</th></tr></thead>
          <tbody>${stage.items.map((item, index) => `<tr><td>${String(index + 1).padStart(2, "0")}</td><th scope="row">${esc(item.name)}</th><td><b>${score(item.cap, 0)}</b></td><td><code>${esc(item.formula)}</code></td><td>${esc(item.description)}</td></tr>`).join("")}</tbody>
        </table>
      </div>
      ${stage.notes?.length ? `<ul class="rule-notes">${stage.notes.map((note) => `<li>${esc(note)}</li>`).join("")}</ul>` : ""}
    </article>`).join("");
}

function participantHead(record) {
  const detail = record.kind === "agent" ? record.detail.split(" · ")[0] : record.detail;
  return `<th scope="col"><b>${esc(record.kindLabel)}</b><small>${esc(detail || record.kind)}</small></th>`;
}

// The per-CASE matrix: one row per deduction item, one column per participant. Every cell is the
// recorded deduction, so a reader can compare a run against the scripted baseline item by item.
function deductionMatrix(caseData) {
  const items = caseData.items || [];
  const records = caseData.records || [];
  if (!items.length || !records.length) return "";
  const head = records.map(participantHead).join("");
  const body = items.map((item) => {
    const cells = records.map((record) => {
      const value = record.items?.[item.id] || {};
      const points = value.points ?? 0;
      const raw = value.raw;
      const showRaw = typeof raw === "number" && Math.abs(raw - points) > 0.05;
      return `<td><span class="matrix-points${points > 0 ? "" : " zero"}">−${score(points)}</span>${showRaw ? `<span class="matrix-raw">原始 ${score(raw)}</span>` : ""}</td>`;
    }).join("");
    return `<tr><th scope="row">${esc(item.name)}<small>上限 ${score(item.cap, 0)} · ${esc(item.formula)}</small></th>${cells}</tr>`;
  }).join("");
  const totals = records.map((record) => {
    const sum = items.reduce((total, item) => total + (record.items?.[item.id]?.points ?? 0), 0);
    return `<td>−${score(sum)}</td>`;
  }).join("");
  const scores = records.map((record) => `<td class="matrix-score">${score(record.score)}</td>`).join("");
  return `<section class="case-deductions">
    <h4>逐项扣分明细</h4>
    <div class="matrix-scroll">
      <table class="deduction-matrix">
        <caption class="sr-only">${esc(caseData.title)}每个参与者在每个扣分项上的实扣</caption>
        <thead><tr><th scope="col">扣分项 / 公式</th>${head}</tr></thead>
        <tbody>${body}</tbody>
        <tfoot>
          <tr><th scope="row">合计扣分</th>${totals}</tr>
          <tr><th scope="row">最终得分</th>${scores}</tr>
        </tfoot>
      </table>
    </div>
    <p class="table-help">实扣按该项上限封顶后计入合计；移动端可横向滚动查看其余参与者。</p>
  </section>`;
}

function casualtyCell(record) {
  const c = record.casualties;
  if (!c) return "未记录";
  const amount = (value) => typeof value !== "number" ? "未记录"
    : Number.isInteger(value) ? String(value) : value.toFixed(1);
  const percent = (value) => typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "未记录";
  const total = `<small class="casualty-total">我方总承伤 ${amount(c.selfDamage)} / ${amount(c.selfCapacity)}（${percent(c.selfDamageRatio)}）</small>`;
  const units = Array.isArray(c.selfUnits) ? c.selfUnits : [];
  const detail = units.length
    ? `<details class="casualty-detail"><summary>单位明细（${units.length} 台）</summary><ul>${units.map((unit) => `<li><b>${esc(unit.alias)}</b> ${unit.alive ? "存活" : "阵亡"} · HP ${amount(unit.hp)}/${amount(unit.maxHp)} · 护盾 ${amount(unit.shield)}/${amount(unit.maxShield)} · 承伤 ${percent(unit.damageRatio)}</li>`).join("")}</ul></details>`
    : `<small class="casualty-missing">逐单位明细未记录</small>`;
  return `<b>${c.selfLost}</b> <span>/ ${c.enemyLost}</span>${total}${detail}`;
}

function caseTimePanel(item) {
  const seedColumn = item.displayMode === "time-seed";
  const rows = item.records.map((record) => {
    const baseline = typeof record.baselineSeconds === "number" ? record.baselineSeconds : null;
    const isBaseline = record.kind === "baseline";
    const timeCell = isBaseline || baseline == null
      ? `<b>${duration(record.seconds, "未记录")}</b>${isBaseline ? '<small>脚本基线</small>' : ""}`
      : `<b>${duration(record.seconds, "未记录")}</b><small>/ ${duration(baseline)} 同任务基线</small>`;
    const outcome = record.timeout ? '<span class="result-badge defeat">超时</span>' : "完成";
    return `<tr>
      <td><span class="kind-badge ${esc(record.kind)}">${esc(record.kind)}</span></td>
      <th scope="row"><b class="participant">${esc(record.kindLabel)}</b>${record.detail ? `<small class="participant-detail">${esc(record.detail)}</small>` : ""}</th>
      <td><b class="case-task">${esc(record.task || item.task)}</b></td>
      ${seedColumn ? `<td><b class="case-seed">s${esc(record.seed ?? "未记录")}</b></td>` : ""}
      <td class="case-time">${timeCell}</td>
      <td>${outcome}</td>
    </tr>`;
  }).join("");
  const baselines = [...new Map(item.records
    .filter((record) => typeof record.baselineSeconds === "number")
    .map((record) => [record.task, record.baselineSeconds])).entries()];
  return `<div class="case-table-grid case-time-grid">
    <section>
      <h4>对局用时</h4>
      <div class="table-scroll" tabindex="0">
        <table class="data-table compact-table time-compare-table">
          <thead><tr><th>类型</th><th>参与者</th><th>任务</th>${seedColumn ? "<th>seed</th>" : ""}<th>用时 / 同任务基线</th><th>结果</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="${seedColumn ? 6 : 5}">还没有已保存的对局</td></tr>`}</tbody>
        </table>
      </div>
    </section>
    <section class="case-time-note">
      <h4>怎么比较</h4>
      <p>这里只比较用时和任务 id：每行先写本局用时，再写同一任务 id 的脚本基线用时。没有胜负，只有是否超时${seedColumn ? "；同一任务下 seed 会换地图，所以 seed 逐行标出" : ""}。</p>
      <dl class="case-baselines">${baselines.map(([task, seconds]) => `<div><dt>${esc(task)}</dt><dd>${duration(seconds)}</dd></div>`).join("")}</dl>
      <p class="table-help">基线用时取自同任务的脚本实测存档；用时按 mm:ss 显示。</p>
    </section>
  </div>`;
}

function renderCases() {
  $("#case-board").innerHTML = microData.cases.map((item) => {
    const timeMode = item.displayMode === "time" || item.displayMode === "time-seed";
    const retreat = item.case === "CASE4-Retreat";
    const duel = item.case === "CASE1-duel";
    const environment = timeMode
      ? (item.displayMode === "time-seed"
        ? `固定环境 · task ${esc(item.task)} · seed 见每行`
        : `固定环境 · 任务 ${(item.tasks || [item.task]).map(esc).join(" / ")}`)
      : retreat
        ? `task ${esc(item.task)} · seed 和布局版本见每行`
        : `固定环境 · task ${esc(item.task)} · seed ${esc(item.seed ?? "未记录")}`;
    return `<article class="case-panel">
      <header class="case-header">
        <img src="${esc(item.image)}" alt="${esc(item.imageAlt || `${item.title}固定场景截图`)}" loading="lazy">
        <div><span>${esc(item.label)}${item.scoreVersion ? ` · ${esc(item.scoreVersion)}` : timeMode ? " · 用时对比" : ""}</span><h3>${esc(item.title)}</h3><p>${esc(item.description)}</p></div>
      </header>
      <div class="case-environment"><span>${environment}</span><p>${esc(item.environment)}</p><small>${esc(item.imageCaption || "")}</small></div>
      ${timeMode ? caseTimePanel(item) : `<div class="case-table-grid">
        <section>
          <h4>对局结果</h4>
          <div class="table-scroll" tabindex="0">
            <table class="data-table compact-table">
              <thead><tr><th>类型</th><th>参与者</th>${retreat ? "<th>seed / 布局</th>" : ""}<th>得分</th><th>结果</th>${duel ? "<th>伤亡<small>我方 / 敌方</small></th>" : retreat ? "<th>虫王存活</th>" : ""}<th>用时</th></tr></thead>
              <tbody>${item.records.map((record) => {
                const {selfLost, selfTotal} = record.casualties || {};
                const detail = [record.detail, record.thinking].filter(Boolean).join(" · ");
                return `<tr><td><span class="kind-badge ${esc(record.kind)}">${esc(record.kind)}</span></td>
                  <th scope="row"><b class="participant">${esc(record.kindLabel)}</b>${detail ? `<small class="participant-detail">${esc(detail)}</small>` : ""}</th>
                  ${retreat ? `<td>s${esc(record.seed)} / v${esc(record.layoutVersion)}</td>` : ""}
                  <td><b class="case-score">${score(record.score)}</b></td><td>${esc(record.note)}</td>
                  ${duel ? `<td class="casualty-cell">${casualtyCell(record)}</td>` : retreat ? `<td>${selfTotal - selfLost} / ${selfTotal}</td>` : ""}
                  <td class="case-time"><b>${duration(record.seconds, "未记录")}</b></td></tr>`;
              }).join("") || `<tr><td colspan="${retreat ? 7 : duel ? 6 : 5}">暂无已评分对局</td></tr>`}</tbody>
            </table>
          </div>
        </section>
        ${deductionMatrix(item)}
      </div>`}
      <details class="case-video"><summary>${retreat ? "查看场景演示（旧布局）" : "查看对应录像"}</summary><video controls preload="metadata" src="${esc(item.video)}">当前浏览器不支持视频播放。</video></details>
    </article>`;
  }).join("");
}

/* ---------- overview matrix: one row per tool, one column per scenario ---------- */
// 总表只回答「谁在哪个场景拿了多少分」：一行是（模型 id、工具、思考强度、提供方），一列是一张
// 地图（完整对局）或一个 CASE。完整对局的格子写 stage1+stage3=总分 M编号；CASE 的格子写总分、
// task id（`2_7_4`，不只是 type）、seed，并按 CASE 追加：CASE 01/03/04 标胜负，CASE 02 不标
// （它只有“建成/没建成”），CASE 02/03 另写用时。脚本基线刻意不入表，人类单独占一行，没有
// 对局的格子保持空白。
const MATRIX_MODEL = "deepseek-v4.1-flash";
const MATRIX_PROVIDER = "opencode";
const MATRIX_THINKING = "high";
const MATRIX_TOOL_ORDER = ["Pi", "OpenCode v2", "Codex", "Claude Code", "OpenChamber", "DSH", "CommandCode"];
const MATRIX_HUMAN = "人类";
const MATRIX_SCRIPT = "脚本 AI";

const isMatrixModel = (agent) => /deepseek[-\s]*v4\.1[-\s]*flash/i.test(String(agent?.model || ""));

// "Pi + RWX CLI" / "pi" / "DSH + RWX CLI" all collapse to the harness name; the CLI adaptation is
// recorded separately in the tool column so the row label stays stable across batches.
function matrixTool(raw) {
  return String(raw || "未记录").replace(/\s*\+\s*RWX CLI\s*$/i, "").replace(/^pi$/i, "Pi");
}

function matrixResult(outcome) {
  if (outcome === "win") return ["win", "胜", "胜利"];
  if (outcome === "defeat") return ["defeat", "负", "战败"];
  if (outcome === "draw") return ["draw", "平", "平局"];
  return ["unknown", "未知", "结果未记录"];
}

// CASE records only carry a Chinese note ("成功" / "失败" / "胜利"), not an outcome key.
function caseOutcome(note) {
  const text = String(note || "");
  if (text.includes("失败")) return "defeat";
  if (text.includes("成功") || text.includes("胜利")) return "win";
  return "unknown";
}

function buildMatrix() {
  const rows = new Map();
  const scenarios = new Map();
  const rowFor = (tool) => {
    if (!rows.has(tool)) rows.set(tool, {tool, notes: new Set(), cells: new Map()});
    return rows.get(tool);
  };
  const cellFor = (tool, key) => {
    const row = rowFor(tool);
    if (!row.cells.has(key)) row.cells.set(key, []);
    return row.cells.get(key);
  };
  const scenarioFor = (key, kind, label, sub) => {
    if (!scenarios.has(key)) scenarios.set(key, {key, kind, label, sub, runs: 0, best: -Infinity});
    return scenarios.get(key);
  };
  const noteFor = (row, pair) => {
    if (/RWX CLI/i.test(pair.tool?.name || "")) row.notes.add("RWX CLI");
  };

  for (const match of ledgerData.matches || []) {
    // 人类的完整对局也进总表（Stage1 按约定记 0，格子仍是 `0+stage3=total`），复用「人类」行。
    // 脚本 AI 基线局同样 Stage1=0，单独占「脚本 AI」行，避免和 LLM Agent 混在一起比较。
    const humanMatch = match.human === true;
    const scriptMatch = match.scriptAi === true;
    for (const pair of match.pairs || []) {
      if (!isMatrixModel(pair.agent) && !humanMatch && !scriptMatch) continue;
      const tool = humanMatch ? MATRIX_HUMAN : scriptMatch ? MATRIX_SCRIPT : matrixTool(pair.tool?.name);
      const key = `map:${match.map || "未记录地图"}`;
      const scenario = scenarioFor(key, "map", match.map || "未记录地图", "完整对局");
      const total = match.v21?.total;
      scenario.runs += 1;
      scenario.best = Math.max(scenario.best, typeof total === "number" ? total : -Infinity);
      noteFor(rowFor(tool), pair);
      if (humanMatch) rowFor(tool).notes.add("手工操作");
      if (scriptMatch) rowFor(tool).notes.add("fast:8 诊断档 · 不可上榜");
      cellFor(tool, key).push({
        kind: "match",
        outcome: match.result?.outcome,
        total,
        stage1: match.v21?.stage1,
        stage3: match.v21?.stage3,
        code: matchCode(match),
        opponent: match.opponent,
        scriptAi: scriptMatch,
        fluency: match.fluency || null,
      });
    }
  }

  for (const caseData of microData.cases || []) {
    const key = `case:${caseData.case}`;
    const timeMode = caseData.displayMode === "time" || caseData.displayMode === "time-seed";
    scenarioFor(key, "case", caseData.case, timeMode ? `${caseData.label} · 用时` : caseData.label);
    for (const record of caseData.records || []) {
      if (caseData.case === "CASE4-Retreat" && record.kind === "agent" && !isMatrixModel({model: record.kindLabel})) continue;
      const baselineRecord = record.kind === "baseline";
      if (baselineRecord && !timeMode) continue;
      const human = record.kind === "human";
      const tool = baselineRecord ? MATRIX_SCRIPT : human ? MATRIX_HUMAN : matrixTool(String(record.detail || "").split(" ")[0]);
      const row = rowFor(tool);
      if (human) row.notes.add("手工操作");
      if (baselineRecord) row.notes.add("CASE 基线为 1× 实时用时");
      const scenario = scenarios.get(key);
      scenario.runs += 1;
      if (timeMode) {
        cellFor(tool, key).push({
          kind: "case-time",
          caseKey: caseData.case,
          task: record.task || caseData.task,
          seed: caseData.displayMode === "time-seed" ? (record.seed ?? null) : null,
          seconds: record.seconds,
          baselineSeconds: record.baselineSeconds ?? null,
          timeout: record.timeout === true,
          baseline: baselineRecord,
        });
        continue;
      }
      const seedMatch = /·\s*s(\d+)/.exec(record.run || "");
      const attemptMatch = /^[A-Za-z]+\s+(\d{2})\s*·/.exec(record.detail || "");
      const total = record.score;
      scenario.best = Math.max(scenario.best, typeof total === "number" ? total : -Infinity);
      cellFor(tool, key).push({
        kind: "case",
        caseKey: caseData.case,
        outcome: caseOutcome(record.note),
        total,
        // 完整 task id（`2_7_4`）比只显示 type 更容易对回该 CASE 的任务表。
        task: String(record.task || caseData.task || "未记录"),
        seed: seedMatch ? seedMatch[1] : (caseData.seed ?? "未记录"),
        attempt: attemptMatch ? attemptMatch[1] : null,
        seconds: typeof record.seconds === "number" ? record.seconds : null,
      });
    }
  }

  const rank = (row) => {
    const index = MATRIX_TOOL_ORDER.indexOf(row.tool);
    if (index !== -1) return index;
    return row.tool === MATRIX_HUMAN ? 99 : 50;
  };
  const byScenario = (kind) => [...scenarios.values()]
    .filter((scenario) => scenario.kind === kind)
    .sort((a, b) => b.runs - a.runs || b.best - a.best || a.label.localeCompare(b.label, "zh-CN"));
  return {
    rows: [...rows.values()].sort((a, b) => rank(a) - rank(b) || a.tool.localeCompare(b.tool, "zh-CN")),
    maps: byScenario("map"),
    // CASE columns keep the CASE 01 → CASE 04 order instead of the run-count order.
    cases: [...scenarios.values()]
      .filter((scenario) => scenario.kind === "case")
      .sort((a, b) => String(a.sub).localeCompare(String(b.sub), "zh-CN")),
  };
}

// 完整对局大多是对 AI：格子第二行在 M 编号后补一个难度标签，避免同一列里"中等"和"困难"被当成同一种对手。
const DIFFICULTY_NAMES = {
  "very easy": "非常简单", easy: "简单", medium: "中等", hard: "困难",
  "very hard": "非常困难", impossible: "不可能",
};

function opponentLabel(text) {
  const raw = String(text || "").trim();
  if (!raw || raw === "unknown") return "";
  const names = [...raw.matchAll(/AI\s*-\s*([A-Za-z]+(?:[- ][A-Za-z]+)?)/g)]
    .map((found) => found[1].replace(/\s+/g, " ").trim().toLowerCase());
  if (!names.length) return "";
  const label = [...new Set(names)].map((name) => DIFFICULTY_NAMES[name] || name).join(" / ");
  const mode = /(\d+v\d+)/i.exec(raw)?.[1];
  return mode ? `${mode} · AI ${label}` : `AI ${label}`;
}

function matrixEntry(entry) {
  const [outcomeClass, outcomeText, outcomeTitle] = matrixResult(entry.outcome);
  const badge = `<span class="result-badge ${outcomeClass}" title="${esc(outcomeTitle)}">${esc(outcomeText)}</span>`;
  if (entry.kind === "match") {
    const opponent = opponentLabel(entry.opponent);
    const meta = [entry.code, entry.scriptAi ? "脚本基线" : null, opponent].filter(Boolean).join(" · ");
    const fluency = entry.fluency
      ? `<small class="matrix-meta matrix-fluency" title="${esc(FLUENCY_HELP)}"><span>流 ${score(entry.fluency.score)} · μ ${fixed(entry.fluency.mu)}</span><span>q ${fixed(entry.fluency.dead, 2)} · CV ${cvText(entry.fluency.cv)} · ${esc(fluencyMaterial(entry.fluency.material))}</span></small>`
      : "";
    return `<span class="matrix-run">${badge}<code class="matrix-equation">${score(entry.stage1)}+${score(entry.stage3)}=${score(entry.total)}</code>${meta ? `<small class="matrix-meta">${esc(meta)}</small>` : ""}${fluency}</span>`;
  }
  if (entry.kind === "case-time") {
    const baseline = typeof entry.baselineSeconds === "number" && entry.baselineSeconds !== entry.seconds
      ? ` / ${duration(entry.baselineSeconds)}` : "";
    const bits = [entry.task, entry.seed != null ? `s${entry.seed}` : null].filter(Boolean).join(" · ");
    const badge = entry.timeout ? `<span class="result-badge defeat" title="超时">超时</span>` : "";
    return `<span class="matrix-run">${badge}<b class="matrix-score">${duration(entry.seconds)}${baseline}</b><small class="matrix-meta">${esc(bits)}</small></span>`;
  }
  const attempt = entry.attempt ? ` · 第 ${Number(entry.attempt)} 次` : "";
  // CASE 01/04 也把本局用时露出来，方便和完整对局的评分时长对照。
  const showOutcome = entry.caseKey !== "CASE2-LTE";
  const showSeconds = entry.seconds != null;
  const parts = [entry.task, `s${entry.seed}`];
  if (showSeconds && entry.seconds != null) parts.push(`用时 ${duration(entry.seconds)}`);
  return `<span class="matrix-run">${showOutcome ? badge : ""}<b class="matrix-score">${score(entry.total)}</b><small class="matrix-meta">${esc(`${parts.join(" · ")}${attempt}`)}</small></span>`;
}

// 冻结前 4 列与表头：把实测列宽/行高写进 CSS 变量，粘性单元格用它们算 left/top。
function fitMatrixPins(table) {
  const row = table?.querySelector("thead tr:first-child");
  const cells = row ? [...row.children] : [];
  if (cells.length < 4) return;
  const [model, tool, thinking] = cells.slice(0, 3).map((cell) => cell.getBoundingClientRect().width);
  table.style.setProperty("--matrix-col-1", `${model}px`);
  table.style.setProperty("--matrix-col-2", `${tool}px`);
  table.style.setProperty("--matrix-col-3", `${thinking}px`);
  table.style.setProperty("--matrix-head-1", `${row.getBoundingClientRect().height}px`);
}

// 鼠标拖动 / 上下方向键调整总表高度；高度写进 localStorage，下次打开保留。
const MATRIX_HEIGHT_KEY = "rwx-matrix-height";
function bindMatrixResize(handle, box, table) {
  if (!handle || !box) return;
  const clamp = (height) => Math.min(Math.max(Math.round(height), 220), Math.round(window.innerHeight * 0.9));
  const remember = (height) => { try { localStorage.setItem(MATRIX_HEIGHT_KEY, String(height)); } catch (error) { /* private mode */ } };
  try {
    const saved = Number(localStorage.getItem(MATRIX_HEIGHT_KEY));
    if (Number.isFinite(saved) && saved > 0) box.style.height = `${clamp(saved)}px`;
  } catch (error) { /* private mode */ }
  let pointerId = null;
  let startY = 0;
  let startHeight = 0;
  const finish = () => {
    if (pointerId !== null && handle.hasPointerCapture(pointerId)) handle.releasePointerCapture(pointerId);
    pointerId = null;
    document.body.classList.remove("resizing-matrix");
    remember(box.getBoundingClientRect().height);
    fitMatrixPins(table);
  };
  handle.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    pointerId = event.pointerId;
    startY = event.clientY;
    startHeight = box.getBoundingClientRect().height;
    try { handle.setPointerCapture(pointerId); } catch (error) { /* synthetic pointer */ }
    document.body.classList.add("resizing-matrix");
  });
  handle.addEventListener("pointermove", (event) => {
    if (pointerId !== event.pointerId) return;
    box.style.height = `${clamp(startHeight + event.clientY - startY)}px`;
    fitMatrixPins(table);
  });
  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
  handle.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    const height = clamp(box.getBoundingClientRect().height + (event.key === "ArrowDown" ? 32 : -32));
    box.style.height = `${height}px`;
    remember(height);
    fitMatrixPins(table);
  });
}

function renderOverviewMatrix() {
  const target = $("#overview-matrix-body");
  if (!target) return;
  const {rows, maps, cases} = buildMatrix();
  if (!rows.length || !maps.length + !cases.length) {
    target.innerHTML = `<p class="load-error">当前数据里还没有可入表的对局。</p>`;
    return;
  }
  const columns = [...maps, ...cases];
  const head = `<thead>
      <tr>
        <th scope="col" rowspan="2" class="matrix-col-model matrix-pin matrix-pin-1">模型 id</th>
        <th scope="col" rowspan="2" class="matrix-col-tool matrix-pin matrix-pin-2">工具</th>
        <th scope="col" rowspan="2" class="matrix-col-thinking matrix-pin matrix-pin-3">思考强度</th>
        <th scope="col" rowspan="2" class="matrix-col-provider matrix-pin matrix-pin-4">提供方</th>
        <th scope="colgroup" colspan="${maps.length}" class="matrix-group-head">完整对局 · 地图</th>
        <th scope="colgroup" colspan="${cases.length}" class="matrix-group-head">Micro CASE</th>
      </tr>
      <tr>
        ${maps.map((column) => `<th scope="col">${esc(column.label)}</th>`).join("")}
        ${cases.map((column) => `<th scope="col"><b>${esc(column.label)}</b><small>${esc(column.sub || "")}</small></th>`).join("")}
      </tr>
    </thead>`;
  const body = rows.map((row) => {
    const human = row.tool === MATRIX_HUMAN;
    const script = row.tool === MATRIX_SCRIPT;
    const plain = human || script;
    const cells = columns.map((column) => {
      const entries = row.cells.get(column.key) || [];
      return `<td class="matrix-cell${entries.length ? "" : " is-empty"}">${entries.map(matrixEntry).join("")}</td>`;
    }).join("");
    return `<tr>
        <th scope="row" class="matrix-model matrix-pin matrix-pin-1">${esc(human ? MATRIX_HUMAN : script ? MATRIX_SCRIPT : MATRIX_MODEL)}</th>
        <td class="matrix-tool matrix-pin matrix-pin-2"><b>${esc(human ? "手工操作" : script ? "AI Hard-up 基线" : row.tool)}</b>${!human && row.notes.size ? `<small>${esc([...row.notes].join(" · "))}</small>` : ""}</td>
        <td class="matrix-thinking matrix-pin matrix-pin-3">${esc(plain ? "不适用" : MATRIX_THINKING)}</td>
        <td class="matrix-provider matrix-pin matrix-pin-4">${esc(plain ? "不适用" : MATRIX_PROVIDER)}</td>
        ${cells}
      </tr>`;
  }).join("");
  target.innerHTML = `<p class="matrix-status">${rows.length} 行参与者 · ${maps.length} 张地图 · ${cases.length} 个 CASE · 脚本 AI 基线单独成行（完整对局 fast:8；CASE 02/03 为 1× 实时用时）</p>
    <div class="table-scroll matrix-table-scroll" tabindex="0" aria-label="总表，可横向滚动">
      <table class="data-table score-matrix">
        <caption>总表：每个工具在地图（完整对局）与 Micro CASE 上的成绩；完整对局的格子写 stage1+stage3=总分、M 编号、对局来源与操作流畅度四元组，CASE 01/04 写分数，CASE 02/03 只写用时 / 同任务基线（CASE 02 另标 seed）</caption>
        ${head}
        <tbody>${body}</tbody>
      </table>
    </div>
    <div class="matrix-resize-handle" role="separator" tabindex="0" aria-label="拖动或用上下方向键调整总表高度" aria-orientation="horizontal"><span aria-hidden="true"></span></div>
    <p class="matrix-legend">格子里的四元组：<b>流</b> = 操作流畅度（0–100）；<b>μ</b> = 加权操作 / 分钟；<b>q</b> = 超过 8 秒发呆的时长占比；<b>CV</b> = 30 秒窗口操作数的变异系数。行尾的「原生 / 降级」表示命令流是否带坐标（native / live），降级局的 μ 与 CV 会系统性偏高。流畅度是附加分，不计入 stage1+stage3=总分。<b>CASE 02 / 03</b> 只比较用时与任务 id：格子写「本局用时 / 同任务脚本基线用时」，没有胜负，只有超时。</p>`;
  const table = target.querySelector("table");
  if (table) {
    requestAnimationFrame(() => fitMatrixPins(table));
    window.addEventListener("resize", () => fitMatrixPins(table), {passive: true});
    bindMatrixResize(target.querySelector(".matrix-resize-handle"), target.querySelector(".matrix-table-scroll"), table);
  }
}

function renderMethod() {
  const limits = [...(ledgerData.method?.limits || [])];
  const ignored = ledgerData.ignored?.length || 0;
  if (ignored > 0) limits.unshift(`另有 ${ignored} 局材料未进入本表（重放分叉或材料不完整），仍保留在 results.json 的 ignored 字段中。`);
  $("#method-limits").innerHTML = limits.map((limit) => `<li>${esc(limit)}</li>`).join("") || "<li>当前批次没有额外限制记录。</li>";
}

// Keep the ledger column headers in sync with the v2.1 scoring ledger instead of a second list.
function applyDeductionLabels() {
  const rules = stage3Rule()?.items || [];
  const byKey = new Map(DEDUCTIONS.map(({key}, index) => [key, rules[index]]));
  for (const header of document.querySelectorAll("#match-ledger thead th[data-deduction-key]")) {
    const key = header.dataset.deductionKey;
    const rule = byKey.get(key);
    if (!rule?.name) continue;
    header.innerHTML = `${esc(rule.name)}<small>${esc(key.toUpperCase())}</small>`;
    header.title = rule.description || "";
  }
}

function bindInteractions() {
  for (const control of [$("#match-search"), $("#outcome-filter"), $("#sort-matches")]) {
    control.addEventListener(control.tagName === "INPUT" ? "input" : "change", renderMatchTable);
  }
  $("#match-table-body").addEventListener("click", (event) => {
    const button = event.target.closest(".match-expand");
    if (!button) return;
    const id = button.dataset.matchId;
    if (openMatches.has(id)) openMatches.delete(id); else openMatches.add(id);
    const detail = document.getElementById(button.getAttribute("aria-controls"));
    const expanded = openMatches.has(id);
    button.setAttribute("aria-expanded", String(expanded));
    button.setAttribute("aria-label", button.getAttribute("aria-label").replace(expanded ? "展开" : "收起", expanded ? "收起" : "展开"));
    detail.hidden = !expanded;
  });
}

function bindNavigation() {
  const toggle = $(".menu-toggle");
  const navigation = $("#primary-nav");
  const close = () => {
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "展开导航");
    navigation.classList.remove("open");
  };
  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "收起导航" : "展开导航");
    navigation.classList.toggle("open", open);
  });
  navigation.addEventListener("click", (event) => { if (event.target.closest("a")) close(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });
}

async function loadJson(path) {
  // `no-cache` forces a revalidation on every load. Without it a browser may keep serving a
  // cached results.json long after it changed, and the page silently renders an old schema.
  const response = await fetch(new URL(path, import.meta.url), {cache: "no-cache"});
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

// An old results.json has no v2.1 block, which used to surface as a table full of "未记录".
// Fail with an actionable message instead of pretending the data is missing.
function assertCurrentLedger(data) {
  const stale = [];
  if (!data.overview21) stale.push("overview21");
  if (!data.standard21) stale.push("standard21");
  if (!data.matches?.every((match) => match.v21)) stale.push("matches[].v21");
  if (stale.length) {
    const error = new Error(`results.json 是旧版本（缺 ${stale.join(" / ")}）`);
    error.stale = true;
    throw error;
  }
}

async function initialize() {
  try {
    [ledgerData, scoringData, microData, matchIds] = await Promise.all([
      loadJson("./resource/results.json"),
      loadJson("./resource/scoring.json"),
      loadJson("./resource/micro-results.json"),
      loadJson("./resource/match-ids.json"),
    ]);
    assertCurrentLedger(ledgerData);
    renderKpis();
    applyDeductionLabels();
    renderOverviewMatrix();
    renderMatchTable();
    renderRuleTables();
    renderCases();
    renderMethod();
    bindInteractions();
  } catch (error) {
    $("#match-filter-status").textContent = "数据加载失败";
    $("#match-table-body").innerHTML = `<tr><td colspan="15" class="empty-state">评测数据暂时无法加载。请通过 HTTP 服务打开页面。</td></tr>`;
    $("#full-rule-tables").innerHTML = `<p class="load-error">评分细则暂时无法加载。</p>`;
    $("#case-board").innerHTML = `<p class="load-error">CASE 数据暂时无法加载。</p>`;
    $("#overview-matrix-body").innerHTML = `<p class="load-error">总表暂时无法加载。</p>`;
    if (error.stale) {
      $("#results-kpis").innerHTML = `<div><span>数据版本过旧</span><b>需要刷新</b><small>${esc(error.message)}</small></div>`;
      $("#match-table-body").innerHTML = `<tr><td colspan="15" class="empty-state">浏览器给的是缓存里的旧 <code>results.json</code>。按 Ctrl+F5（macOS：Cmd+Shift+R）强制刷新即可；页面已改为每次校验缓存，之后不会再出现。</td></tr>`;
      $("#method-limits").innerHTML = `<li>${esc(error.message)}：请强制刷新页面重新加载数据。</li>`;
    }
    console.error(error);
  }
}

bindNavigation();
initialize();
