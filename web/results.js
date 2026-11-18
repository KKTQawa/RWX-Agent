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
  return `<tr class="match-detail-row" id="${esc(detailId)}"${openMatches.has(match.id) ? "" : " hidden"}><td colspan="14"><div class="match-detail-panel">
    <section class="match-facts"><h3>对局与材料</h3><dl>
      <div><dt>编号</dt><dd>${esc(matchCode(match) || "未分配")}</dd></div>
      <div><dt>完整标题</dt><dd>${esc(match.title)}</dd></div><div><dt>地图</dt><dd>${esc(match.map || "未记录")}</dd></div>
      <div><dt>对手 / 规则</dt><dd>${esc(match.opponent || "未记录")}</dd></div><div><dt>结局</dt><dd>${esc(outcomeLabel(match.result?.outcome))}${match.result?.atSeconds != null ? ` · ${duration(match.result.atSeconds)}` : ""}</dd></div>
      <div><dt>评分窗口</dt><dd>${duration(v21.windowSeconds ?? match.duration?.scoreSeconds)}</dd></div><div><dt>游戏时长</dt><dd>${duration(gameSeconds, "材料只记录了评分窗口")}</dd></div>
      <div><dt>证据来源</dt><dd>${esc(evidenceLabel(match.evidenceSource))}</dd></div><div><dt>评分版本</dt><dd>${esc(ledgerData.standard21?.stage3 || "stage3-score-v2.1-v3")}</dd></div>
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
    if (sort === "delta-desc") return (b.v21?.delta ?? 0) - (a.v21?.delta ?? 0);
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
    const delta = v21.delta;
    // Second line of the duration cell always carries real information: the game length when the
    // materials recorded it, otherwise where the numbers came from.
    const gameNote = typeof match.duration?.gameSeconds === "number"
      ? `游戏 ${duration(match.duration.gameSeconds)}`
      : evidenceLabel(match.evidenceSource);
    return `<tr class="match-row">
      <td class="expand-cell"><button class="match-expand" type="button" data-match-id="${esc(match.id)}" aria-expanded="${expanded}" aria-controls="${esc(detailId)}" aria-label="${expanded ? "收起" : "展开"}${esc(match.title)}的扣分详情"><span aria-hidden="true"></span></button></td>
      <th scope="row" class="match-name-cell"><span class="row-index">${esc(matchCode(match) || String(index + 1).padStart(2, "0"))}</span><div><b>${esc(match.title)}</b><small>${esc(dateLabel(match.date))}</small></div></th>
      <td class="pair-cell"><b>${esc(pairText(match.pairs))}</b>${match.pairs?.some((pair) => pair.tool?.extra) ? `<small>${esc(match.pairs.map((pair) => pair.tool?.extra).filter(Boolean).join(" / "))}</small>` : ""}</td>
      <td class="map-cell"><b>${esc(match.map || "未记录")}</b><small>${esc(match.opponent || "未记录")}</small></td>
      <td><span class="result-badge ${esc(result.outcome || "unknown")}">${esc(outcomeLabel(result.outcome))}</span><small class="cell-note">${result.atSeconds != null ? duration(result.atSeconds) : "时长未记录"}</small></td>
      <td class="score-cell"><strong class="total-score ${scoreTier(v21.total)}">${score(v21.total)}</strong><small>/ 100</small></td>
      <td class="stage-score"><strong>${score(v21.stage1)}</strong><small>/ 100</small></td>
      <td class="stage-score"><strong>${score(v21.stage3)}</strong><small>/ 100</small></td>
      ${DEDUCTIONS.map(({key}) => `<td class="deduction-cell">${deductionCell(key, items[key])}</td>`).join("")}
      <td class="delta-cell"><strong class="delta-value ${delta > 0 ? "up" : "flat"}">${signed(delta)}</strong><small>v2 ${score(v21.v2?.total)}</small></td>
      <td class="duration-cell"><b>${duration(v21.windowSeconds ?? match.duration?.scoreSeconds)}</b><small>${esc(gameNote)}</small></td>
    </tr>${renderMatchDetail(match, detailId)}`;
  }).join("") || `<tr><td colspan="14" class="empty-state">没有符合当前筛选条件的对局。</td></tr>`;
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

function renderCases() {
  $("#case-board").innerHTML = microData.cases.map((item) => `
    <article class="case-panel">
      <header class="case-header">
        <img src="${esc(item.image)}" alt="${esc(item.imageAlt || `${item.title}固定场景截图`)}" loading="lazy">
        <div><span>${esc(item.label)} · ${esc(item.scoreVersion || "")}</span><h3>${esc(item.title)}</h3><p>${esc(item.description)}</p></div>
      </header>
      <div class="case-environment"><span>固定环境 · task ${esc(item.task)} · seed ${esc(item.seed ?? "未记录")}</span><p>${esc(item.environment)}</p><small>${esc(item.imageCaption || "")}</small></div>
      <div class="case-table-grid">
        <section>
          <h4>对局结果</h4>
          <div class="table-scroll" tabindex="0">
            <table class="data-table compact-table">
              <thead><tr><th>类型</th><th>参与者</th><th>得分</th><th>结果</th><th>时长</th></tr></thead>
              <tbody>${item.records.map((record) => `<tr><td><span class="kind-badge ${esc(record.kind)}">${esc(record.kind)}</span></td><th scope="row"><b class="participant">${esc(record.kindLabel)}</b>${record.detail ? `<small class="participant-detail">${esc(record.detail)}</small>` : ""}</th><td><b class="case-score">${score(record.score)}</b></td><td>${esc(record.note)}</td><td>${duration(record.seconds, "未记录")}</td></tr>`).join("")}</tbody>
            </table>
          </div>
        </section>
        ${deductionMatrix(item)}
      </div>
      <details class="case-video"><summary>查看对应录像</summary><video controls preload="metadata" src="${esc(item.video)}">当前浏览器不支持视频播放。</video></details>
    </article>`).join("");
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
    const humanMatch = match.human === true;
    for (const pair of match.pairs || []) {
      if (!isMatrixModel(pair.agent) && !humanMatch) continue;
      const tool = humanMatch ? MATRIX_HUMAN : matrixTool(pair.tool?.name);
      const key = `map:${match.map || "未记录地图"}`;
      const scenario = scenarioFor(key, "map", match.map || "未记录地图", "完整对局");
      const total = match.v21?.total;
      scenario.runs += 1;
      scenario.best = Math.max(scenario.best, typeof total === "number" ? total : -Infinity);
      noteFor(rowFor(tool), pair);
      if (humanMatch) rowFor(tool).notes.add("手工操作");
      cellFor(tool, key).push({
        kind: "match",
        outcome: match.result?.outcome,
        total,
        stage1: match.v21?.stage1,
        stage3: match.v21?.stage3,
        code: matchCode(match),
        opponent: match.opponent,
      });
    }
  }

  for (const caseData of microData.cases || []) {
    const key = `case:${caseData.case}`;
    scenarioFor(key, "case", caseData.case, caseData.label);
    for (const record of caseData.records || []) {
      if (record.kind === "baseline") continue;
      const human = record.kind === "human";
      const tool = human ? MATRIX_HUMAN : matrixTool(String(record.detail || "").split(" ")[0]);
      const row = rowFor(tool);
      if (human) row.notes.add("手工操作");
      const seedMatch = /·\s*s(\d+)/.exec(record.run || "");
      const attemptMatch = /^[A-Za-z]+\s+(\d{2})\s*·/.exec(record.detail || "");
      const total = record.score;
      const scenario = scenarios.get(key);
      scenario.runs += 1;
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
    const meta = [entry.code, opponent].filter(Boolean).join(" · ");
    return `<span class="matrix-run">${badge}<code class="matrix-equation">${score(entry.stage1)}+${score(entry.stage3)}=${score(entry.total)}</code>${meta ? `<small class="matrix-meta">${esc(meta)}</small>` : ""}</span>`;
  }
  const attempt = entry.attempt ? ` · 第 ${Number(entry.attempt)} 次` : "";
  // CASE 02 只有“建成/没建成”，没有胜负可言；CASE 02/03 的用时是评分输入（时长扣分），要露出来。
  const showOutcome = entry.caseKey !== "CASE2-LTE";
  const showSeconds = entry.caseKey === "CASE2-LTE" || entry.caseKey === "CASE3-Transport";
  const parts = [entry.task, `s${entry.seed}`];
  if (showSeconds && entry.seconds != null) parts.push(`用时 ${duration(entry.seconds)}`);
  return `<span class="matrix-run">${showOutcome ? badge : ""}<b class="matrix-score">${score(entry.total)}</b><small class="matrix-meta">${esc(`${parts.join(" · ")}${attempt}`)}</small></span>`;
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
        <th scope="col" rowspan="2" class="matrix-col-model">模型 id</th>
        <th scope="col" rowspan="2" class="matrix-col-tool">工具</th>
        <th scope="col" rowspan="2" class="matrix-col-thinking">思考强度</th>
        <th scope="col" rowspan="2" class="matrix-col-provider">提供方</th>
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
    const cells = columns.map((column) => {
      const entries = row.cells.get(column.key) || [];
      return `<td class="matrix-cell${entries.length ? "" : " is-empty"}">${entries.map(matrixEntry).join("")}</td>`;
    }).join("");
    return `<tr>
        <th scope="row" class="matrix-model">${esc(human ? MATRIX_HUMAN : MATRIX_MODEL)}</th>
        <td class="matrix-tool"><b>${esc(human ? "手工操作" : row.tool)}</b>${!human && row.notes.size ? `<small>${esc([...row.notes].join(" · "))}</small>` : ""}</td>
        <td class="matrix-thinking">${esc(human ? "不适用" : MATRIX_THINKING)}</td>
        <td class="matrix-provider">${esc(human ? "不适用" : MATRIX_PROVIDER)}</td>
        ${cells}
      </tr>`;
  }).join("");
  target.innerHTML = `<p class="matrix-status">${rows.length} 行参与者 · ${maps.length} 张地图 · ${cases.length} 个 CASE · 脚本基线不入表</p>
    <div class="table-scroll matrix-table-scroll" tabindex="0" aria-label="总表，可横向滚动">
      <table class="data-table score-matrix">
        <caption>总表：每个工具在地图（完整对局）与 Micro CASE 上的总分；完整对局另写 stage1+stage3=总分与 M 编号，CASE 另写 task id、seed 与用时</caption>
        ${head}
        <tbody>${body}</tbody>
      </table>
    </div>`;
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
    $("#match-table-body").innerHTML = `<tr><td colspan="14" class="empty-state">评测数据暂时无法加载。请通过 HTTP 服务打开页面。</td></tr>`;
    $("#full-rule-tables").innerHTML = `<p class="load-error">评分细则暂时无法加载。</p>`;
    $("#case-board").innerHTML = `<p class="load-error">CASE 数据暂时无法加载。</p>`;
    $("#overview-matrix-body").innerHTML = `<p class="load-error">总表暂时无法加载。</p>`;
    if (error.stale) {
      $("#results-kpis").innerHTML = `<div><span>数据版本过旧</span><b>需要刷新</b><small>${esc(error.message)}</small></div>`;
      $("#match-table-body").innerHTML = `<tr><td colspan="14" class="empty-state">浏览器给的是缓存里的旧 <code>results.json</code>。按 Ctrl+F5（macOS：Cmd+Shift+R）强制刷新即可；页面已改为每次校验缓存，之后不会再出现。</td></tr>`;
      $("#method-limits").innerHTML = `<li>${esc(error.message)}：请强制刷新页面重新加载数据。</li>`;
    }
    console.error(error);
  }
}

bindNavigation();
initialize();
