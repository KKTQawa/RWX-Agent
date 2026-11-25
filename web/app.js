const video = document.querySelector("#match-video");
const matchButtons = [...document.querySelectorAll("[data-match]")];
const playerStatus = document.querySelector("#playback-status");
const videoError = document.querySelector("#video-error");
const matches = new Map();
let selectedId = "very-hard";

function announce(text) {
  playerStatus.textContent = text;
}

function playCurrent() {
  const attempt = video.play();
  if (attempt) attempt.catch(() => announce("录像已就绪，请使用播放器的播放按钮。"));
}

function selectMatch(id, play = true) {
  const match = matches.get(id);
  if (!match) {
    announce("录像列表尚未加载完成，请稍后重试。");
    return;
  }
  if (selectedId !== id) {
    video.pause();
    video.src = match.video;
    video.poster = match.poster;
    video.setAttribute("aria-label", match.title + "对局录像");
    video.load();
  }
  selectedId = id;
  videoError.hidden = true;
  document.querySelector("#match-category").textContent = match.category;
  document.querySelector("#match-title").textContent = match.title;
  document.querySelector("#match-description").textContent = match.description;
  document.querySelector("#video-link").href = match.video;
  document.querySelector("#video-error-link").href = match.video;
  for (const button of matchButtons) {
    const active = button.dataset.match === id;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  announce("已选择：" + match.title);
  if (play) playCurrent();
}

const recordingsReady = fetch(new URL("./resource/matches.json", import.meta.url))
  .then(response => {
    if (!response.ok) throw new Error("Recording manifest unavailable");
    return response.json();
  })
  .then(recordings => {
    for (const match of recordings) {
      matches.set(match.id, match);
      const button = matchButtons.find(item => item.dataset.match === match.id);
      if (button) button.querySelector(".match-thumb > span").textContent = match.durationLabel;
    }
    selectMatch(selectedId, false);
  })
  .catch(() => announce("录像索引暂时无法加载，仍可使用播放器观看第一场对局。"));

for (const button of matchButtons) {
  button.addEventListener("click", async () => {
    await recordingsReady;
    selectMatch(button.dataset.match);
  });
}
for (const link of document.querySelectorAll("[data-play-match]")) {
  link.addEventListener("click", async () => {
    await recordingsReady;
    selectMatch(link.dataset.playMatch);
  });
}
video.addEventListener("error", () => {
  videoError.hidden = false;
  announce("录像加载失败，可以尝试在新窗口直接打开视频。");
});
video.addEventListener("playing", () => {
  videoError.hidden = true;
  announce("正在播放：" + document.querySelector("#match-title").textContent);
});

const menuToggle = document.querySelector(".menu-toggle");
const navigation = document.querySelector("#primary-nav");
function closeMenu() {
  menuToggle.setAttribute("aria-expanded", "false");
  navigation.classList.remove("open");
  menuToggle.setAttribute("aria-label", "展开导航");
}
menuToggle.addEventListener("click", () => {
  const open = menuToggle.getAttribute("aria-expanded") !== "true";
  menuToggle.setAttribute("aria-expanded", String(open));
  menuToggle.setAttribute("aria-label", open ? "收起导航" : "展开导航");
  navigation.classList.toggle("open", open);
});
navigation.addEventListener("click", event => {
  if (event.target.closest("a")) closeMenu();
});
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && menuToggle.getAttribute("aria-expanded") === "true") {
    closeMenu();
    menuToggle.focus();
  }
});

const launchCode = document.querySelector("#launch-code");
const commands = {
  windows: "# 获取项目\ngit clone https://github.com/KKTQawa/RWX-Agent.git\ncd RWX-Agent\n\n# 使用 Java 25 启动带 CLI 的游戏\n.\\gradlew.bat :desktop:rwxCliRun",
  linux: "# 获取项目\ngit clone https://github.com/KKTQawa/RWX-Agent.git\ncd RWX-Agent\n\n# 使用 Java 25 启动 Headless 实例\nbash ./gradlew :desktop:run --args='--headless --no-steam'"
};
for (const button of document.querySelectorAll("[data-platform]")) {
  button.addEventListener("click", () => {
    launchCode.textContent = commands[button.dataset.platform];
    for (const other of document.querySelectorAll("[data-platform]")) {
      const active = other === button;
      other.classList.toggle("active", active);
      other.setAttribute("aria-pressed", String(active));
    }
  });
}

const toast = document.querySelector("#toast");
let toastTimer;
function showToast(text) {
  clearTimeout(toastTimer);
  toast.textContent = text;
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 2600);
}
const copyButton = document.querySelector(".copy-button");
copyButton.addEventListener("click", async () => {
  try {
    if (!navigator.clipboard || !window.isSecureContext) throw new Error("Clipboard unavailable");
    await navigator.clipboard.writeText(launchCode.textContent);
    copyButton.querySelector("use").setAttribute("href", "#i-check");
    copyButton.querySelector("span").textContent = "已复制";
    showToast("启动命令已复制");
    setTimeout(() => {
      copyButton.querySelector("use").setAttribute("href", "#i-copy");
      copyButton.querySelector("span").textContent = "复制";
    }, 2200);
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(launchCode);
    selection.removeAllRanges();
    selection.addRange(range);
    showToast("已选中命令，请按 Ctrl+C 或使用系统复制菜单");
  }
});

/* ---------- catalog + progress numbers ----------
   The landing page previews the ledger. Every number below is read from the same JSON the
   results page renders, so the two pages can never disagree. Static markup keeps a sensible
   fallback when the fetch fails. */
const oneDecimal = value => typeof value === "number" ? value.toFixed(1) : null;

function setStat(name, value) {
  if (value == null) return;
  for (const node of document.querySelectorAll(`[data-stat="${name}"]`)) node.textContent = value;
}

function setMeter(name, value) {
  if (typeof value !== "number") return;
  const fill = document.querySelector(`[data-meter="${name}"]`);
  if (!fill) return;
  const width = Math.max(0, Math.min(100, value));
  requestAnimationFrame(() => { fill.style.width = `${width}%`; });
}

async function loadPreview() {
  // Same reason as results.js: revalidate so a cached copy cannot win over a rebuilt file.
  const [ledger, micro] = await Promise.all([
    fetch(new URL("./resource/results.json", import.meta.url), {cache: "no-cache"}).then(response => {
      if (!response.ok) throw new Error("results.json");
      return response.json();
    }),
    fetch(new URL("./resource/micro-results.json", import.meta.url), {cache: "no-cache"}).then(response => {
      if (!response.ok) throw new Error("micro-results.json");
      return response.json();
    }),
  ]);
  if (!ledger.overview21) throw new Error("results.json 是旧版本");

  const overview = ledger.overview21 || {};
  const stage3 = (ledger.matches || []).reduce((sum, match) => sum + (match.v21?.stage3 || 0), 0) / (ledger.matches?.length || 1);
  setStat("average", oneDecimal(overview.average));
  setStat("median", oneDecimal(overview.median));
  setStat("max", oneDecimal(overview.max));
  setStat("delta", typeof overview.averageDelta === "number" ? `+${overview.averageDelta.toFixed(1)}` : null);
  setStat("stage3", oneDecimal(stage3));
  setStat("matches", overview.matches ? `${overview.matches} 局` : null);
  setStat("improved", overview.matches ? `${overview.improved ?? 0}/${overview.matches}` : null);
  setMeter("average", overview.average);
  setMeter("median", overview.median);
  setMeter("max", overview.max);
  setMeter("delta", overview.averageDelta);
  setMeter("stage3", stage3);

  // The three finding cards describe the Agent side — tool, latency, reaction — not the map,
  // the opponent or the scoring rules.
  const toolCard = toolSplit(micro);
  if (toolCard) {
    setStat("tool", `${toolCard.best.average > toolCard.worst.average ? "+" : "−"}${Math.abs(toolCard.best.average - toolCard.worst.average).toFixed(1)}`);
    setVoiceText("tool", `同一个模型（deepseek-v4.1-flash）换工具后的四个 CASE 平均分：${toolCard.best.tool} ${toolCard.best.average.toFixed(1)} / ${toolCard.worst.tool} ${toolCard.worst.average.toFixed(1)}。同一批 task 与 seed，差距只来自工具链。`);
  }
  const latencyCard = latencySplit(micro);
  if (latencyCard) {
    setStat("latency", `${latencyCard.high.points.toFixed(0)} / ${latencyCard.high.cap}`);
    setVoiceText("latency", `${latencyCard.title}的行动延迟：${latencyCard.high.detail.split(" · ")[0]} 打满 ${latencyCard.high.points.toFixed(0)}/${latencyCard.high.cap}，${latencyCard.low.detail.split(" · ")[0]} 只扣 ${latencyCard.low.points.toFixed(1)}。从看到状态到真正下令这一段，仍是主要瓶颈。`);
  }
  const reactionCard = reactionSplit(ledger.matches || []);
  if (reactionCard) {
    setStat("reaction", `−${reactionCard.average.toFixed(1)}`);
    setVoiceText("reaction", `完整对局里偷袭 v3（单位挨打后仍空闲）平均扣 ${reactionCard.average.toFixed(1)}/50，${reactionCard.over}/${reactionCard.total} 局超过 20 分 —— 这是反应速度，不是地图难度。`);
  }

  for (const panel of micro.cases || []) {
    const scores = panel.records.map(record => record.score).filter(value => typeof value === "number");
    const bestCase = scores.length ? Math.max(...scores) : null;
    const timeMode = panel.displayMode === "time" || panel.displayMode === "time-seed";
    const label = document.querySelector(`[data-case-score="${panel.case}"]`);
    if (label) {
      if (timeMode) label.textContent = "用时对比";
      else if (bestCase != null) label.textContent = `最高 ${bestCase.toFixed(1)}`;
    }
    const count = document.querySelector(`[data-case-count="${panel.case}"]`);
    if (count) count.textContent = `${panel.records.length} 局`;
  }
}

function setVoiceText(stat, text) {
  const node = document.querySelector(`[data-stat="${stat}"]`)?.closest(".voice")?.querySelector("p");
  if (node) node.textContent = text;
}

// Average CASE score per harness (Pi / DSH) over the same model and tasks.
// A CASE that has several attempts (CASE 02 ran twice) counts once: average its attempts first,
// then average the CASE means, so one CASE cannot outvote the other three.
function toolSplit(micro) {
  const groups = new Map();
  for (const panel of micro.cases || []) {
    for (const record of panel.records) {
      if (record.kind !== "agent") continue;
      const tool = (record.detail || "").split(" ")[0];
      if (!tool) continue;
      const perCase = groups.get(tool) || new Map();
      const entry = perCase.get(panel.case) || {sum: 0, count: 0};
      entry.sum += record.score;
      entry.count += 1;
      perCase.set(panel.case, entry);
      groups.set(tool, perCase);
    }
  }
  const rows = [...groups].map(([tool, perCase]) => {
    const means = [...perCase.values()].map(entry => entry.sum / entry.count);
    return {tool, average: means.reduce((sum, value) => sum + value, 0) / means.length, count: means.length};
  }).sort((a, b) => b.average - a.average);
  return rows.length >= 2 ? {best: rows[0], worst: rows[rows.length - 1]} : null;
}

// The CASE where two harnesses disagree most on the same delay item.
function latencySplit(micro) {
  let best = null;
  for (const panel of micro.cases || []) {
    const rows = panel.records
      .filter(record => record.kind === "agent" && record.items?.action_delay)
      .map(record => ({...record, points: record.items.action_delay.points, cap: record.items.action_delay.cap}));
    if (rows.length < 2) continue;
    const high = rows.reduce((a, b) => (b.points > a.points ? b : a));
    const low = rows.reduce((a, b) => (b.points < a.points ? b : a));
    const spread = high.points - low.points;
    if (!best || spread > best.spread) best = {spread, high, low, title: panel.title};
  }
  return best;
}

// Mean ambush deduction across the full-match ledger: a unit that keeps idling after being hit.
// Script baselines run in the fast:8 diagnostic profile, so they stay out of the findings.
function reactionSplit(matches) {
  const values = matches.filter(match => !match.scriptAi)
    .map(match => match.v21?.items?.ambush?.deduction).filter(value => typeof value === "number");
  if (!values.length) return null;
  return {
    average: values.reduce((a, b) => a + b, 0) / values.length,
    over: values.filter(value => value > 20).length,
    total: values.length,
  };
}

loadPreview().catch(() => { /* static markup already carries the last published numbers */ });
