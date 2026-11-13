"""CASE4-Retreat deduction score — the executable form of `score_design.md` (case4-score-v1).

Three separate deductions, each capped, then `100 - sum`:

1. **虫王损失 (cap 50)** — `S = K1*50`, `K1` = destroyed task units / task units.
2. **虫王空闲 (cap 30)** — from the engine's 250 game-ms `tank_state` timeline: first
   build the raw intervals in which every tank currently inside a repair bay is at full HP;
   then intersect each tank's in-bay idle raw intervals with those filter intervals
   (a *ready* window, > 3 s). *Loitering* is idling outside every bay (> 8 s) and deliberately
   ignores HP. `w = Σ(A-3)*1.5 + Σ(B-8)*2`, `T` = summed alive time of all tanks and
   `S = 30*(w/T)/R`; windows starting at t=0 or ending at the run end are dropped.
   `R` is 5 % unless `config.json` records a measured baseline `w/T`, then `R = 5 x (w/T)`.
3. **整体时长 (cap 30)** — below `0.6T` the penalty is `30*(1-(x/0.6T)^2)`; inside
   `[0.6T,2.5T]` it is the `a=-3` quadratic through `(0.6T,0)` and `(2.5T,30)`; above `2.5T`
   it is 30. `T` is the measured baseline duration, else the per-type default, else `0.55 x` limit.

Nothing is invented when evidence is missing: the item then reports `status="N/A"` and 0 points.
"""
from __future__ import annotations
import json
from bisect import bisect_right
from pathlib import Path
import sys

CASE = Path(__file__).resolve().parent
sys.path.insert(0, str(CASE.parent))
from common.config import evaluation  # noqa: E402
from common.scoring import cap, curve, document, round1  # noqa: E402

_EVALUATION = evaluation(CASE)
VERSION = _EVALUATION["scoreVersion"]
BASELINE = _EVALUATION.get("scoreBaseline", 100)
TANK_LOSS = _EVALUATION["tankLoss"]
TANK_IDLE = _EVALUATION["tankIdle"]
LOSS_SCALE = TANK_LOSS["scale"]
IDLE_SCALE = TANK_IDLE["scale"]
IDLE_WEIGHTS = TANK_IDLE["weights"]
IDLE_MIN_SECONDS = TANK_IDLE["minSeconds"]
# `R` when no measured baseline w/T exists. The draft calls it "initial 5 %".
IDLE_RATIO_DEFAULT = TANK_IDLE["ratioDefault"]
IDLE_RATIO_MULTIPLIER = TANK_IDLE["ratioMultiplier"]
DROP_BEGIN = TANK_IDLE.get("dropBeginInterval", True)
DROP_TAIL = TANK_IDLE.get("dropTailInterval", True)
DURATION = _EVALUATION["duration"]
QUADRATIC_A = DURATION["quadraticA"]
DURATION_LOWER_RATIO = float(DURATION.get("lowerRatio", 0.6))
DURATION_UPPER_RATIO = float(DURATION.get("upperRatio", 2.5))
# The draft fixes only `a=-3` and the two endpoints. With `T` = the measured baseline (~50 s for
# 4_1_1) a quadratic solved in raw seconds is a step: every run slower than ~0.42T already scores
# 30, so the item would be constant. `normalized` maps [0.4T, 2T] to [0,1] and keeps the curve graded;
# `raw` (CASE3's current default) and `minutes` are available for comparison.
DURATION_QUADRATIC_SPACE = DURATION["quadraticSpace"]
# Full HP is an engine float; 0.001 absorbs representation noise without treating a heal-in-progress
# tank as ready.
FULL_HP_EPSILON = TANK_IDLE["fullHpEpsilon"]


def _tanks(run):
    return sorted((run.tanks or {}).values(), key=lambda row: row["id"])


def _final_alive(run):
    """unitId -> alive from the authoritative final state."""
    rows = {row.get("unitId"): bool(row.get("alive")) for row in (run.result.get("tanks") or [])}
    if rows:
        return rows
    final = run.result.get("units")
    if final:
        return {row["id"]: bool(row.get("alive")) for row in final}
    return None


def tank_loss(run):
    tanks = _tanks(run)
    if not tanks:
        return {"id": "tank_loss", "title": "虫王损失", "status": "N/A",
                "reason": "no tanks in meta", "cap": TANK_LOSS["cap"], "raw": 0.0, "detail": {}}
    final = _final_alive(run)
    if final is None:
        return {"id": "tank_loss", "title": "虫王损失", "status": "N/A",
                "reason": "missing final unit state", "cap": TANK_LOSS["cap"], "raw": 0.0, "detail": {}}
    destroyed = [row["id"] for row in tanks if not final.get(row["id"], True)]
    share = len(destroyed) / len(tanks)
    return {"id": "tank_loss", "title": "虫王损失", "status": "OK", "cap": TANK_LOSS["cap"],
            "raw": share * LOSS_SCALE,
            "detail": {"tanks": len(tanks), "alive": len(tanks) - len(destroyed), "destroyed": len(destroyed),
                       "K1": round(share, 3), "scale": LOSS_SCALE, "destroyedIds": destroyed,
                       "units": [{"unitId": row["id"], "alias": row.get("alias"),
                                  "alive": final.get(row["id"], True)} for row in tanks],
                       "formula": f"K1*{LOSS_SCALE:g}, K1 = destroyed/tanks"}}


def _samples(run):
    """unitId -> list of state rows, sorted by time."""
    samples = {}
    for row in run.tank_state or []:
        moment = row.get("gameMs")
        if moment is None:
            continue
        for tank in row.get("tanks") or []:
            unit = tank.get("unitId")
            if unit is None:
                continue
            samples.setdefault(unit, []).append({
                "ms": float(moment), "alive": bool(tank.get("alive")),
                "order": tank.get("order") or "idle",
                "hp": float(tank.get("hp") or 0.0), "maxHp": float(tank.get("maxHp") or 0.0),
                "bays": [bay for bay in (tank.get("repairBayIds") or []) if bay is not None],
            })
    for rows in samples.values():
        rows.sort(key=lambda row: row["ms"])
    return samples


def _full(sample):
    """HP is at its maximum."""
    return sample["maxHp"] > 0 and sample["hp"] >= sample["maxHp"] - FULL_HP_EPSILON


def _state_at(rows, ms):
    """The tank's last observed state at or before `ms` (None before its first sample)."""
    times = [row["ms"] for row in rows]
    index = bisect_right(times, ms) - 1
    return rows[index] if index >= 0 else None


def _bay_full_intervals(samples, begin_ms, end_ms):
    """Raw intervals in which every tank currently inside a repair bay is at full HP.

    This is the A-side filter, built before any per-tank idle window is cut: every interval is
    `[sample_time_i, sample_time_i+1)`, and its flag comes from the state at the left endpoint.
    A tank's in-bay idle intervals are intersected with these intervals afterwards, so a tank that
    is already full does not count while a baymate is still healing.
    """
    times = {float(begin_ms), float(end_ms)}
    for rows in samples.values():
        for row in rows:
            if begin_ms <= row["ms"] <= end_ms:
                times.add(row["ms"])
    marks = sorted(times)
    intervals = []
    for start, end in zip(marks, marks[1:]):
        if end <= start:
            continue
        inside = []
        for rows in samples.values():
            sample = _state_at(rows, start)
            if sample is not None and sample["alive"] and sample["bays"]:
                inside.append(sample)
        if not inside or not all(_full(sample) for sample in inside):
            continue
        if intervals and intervals[-1][1] == start:
            intervals[-1] = (intervals[-1][0], end)
        else:
            intervals.append((start, end))
    return intervals


def _kind(sample):
    """Raw per-sample label: in-bay idle (`ready` candidate), outside-bay idle (`loiter`) or None."""
    if not sample["alive"] or sample["order"] != "idle":
        return None
    return "ready" if sample["bays"] else "loiter"


def _clip(start, end, intervals):
    """All intersections of [start, end) with the A-filter intervals."""
    for left, right in intervals:
        low, high = max(start, left), min(end, right)
        if high > low:
            yield low, high


def _timeline(rows, begin_ms, end_ms, drop_tail=False):
    """Raw sample intervals for one tank, clipped to [begin_ms, end_ms)."""
    times = [row["ms"] for row in rows]
    for index, row in enumerate(rows):
        start = max(row["ms"], begin_ms)
        if start >= end_ms:
            break
        # The final sample-to-end interval is not an observed idle window: the task may have
        # already been won and the last state row is just the last 250 ms sample.
        if drop_tail and index + 1 >= len(times):
            break
        following = min(times[index + 1], end_ms) if index + 1 < len(times) else end_ms
        if following > start:
            yield start, following, row


def _unit_windows(rows, begin_ms, end_ms, bay_full, drop_tail=False):
    """Maximal ready/loiter intervals for one tank, sliced from the raw sample intervals.

    A `ready` piece is the intersection of an in-bay idle raw interval with `bay_full`; a
    `loiter` piece is an outside-bay idle raw interval and deliberately ignores HP.
    """
    windows = []

    def add(kind, start, end):
        if end <= start:
            return
        if windows and windows[-1]["kind"] == kind and windows[-1]["end"] == start:
            windows[-1]["end"] = end
        else:
            windows.append({"kind": kind, "start": start, "end": end})

    for start, end, sample in _timeline(rows, begin_ms, end_ms, drop_tail):
        kind = _kind(sample)
        if kind is None:
            continue
        if kind == "ready":
            if not _full(sample):
                continue
            for left, right in _clip(start, end, bay_full):
                add("ready", left, right)
        else:
            add("loiter", start, end)
    return windows


def _begin_ms(run):
    """Task start: the first engine sample while `phase=running` (≈ the `begin` lifecycle moment)."""
    times = [rows[0]["ms"] for rows in _samples(run).values() if rows]
    return min(times) if times else 0.0


def _death_ms(run, unit_id):
    tick_ms = float(run.meta.get("tickDurationMs") or 16)
    for kill in run.result.get("kills") or []:
        if kill.get("unit") == unit_id and kill.get("tick") is not None:
            return float(kill["tick"]) * tick_ms
    return None


def _baselines():
    return DURATION


def _idle_reference(run):
    """(R, source): 5× the measured per-type baseline w/T when one exists, else the 5 % default."""
    table = _baselines()
    ratio = (table.get("idleRatioByType") or {}).get(str(run.meta.get("type")))
    source = "per-type baseline"
    # A baseline that never idles gives R = 0, which cannot normalise anything; keep the 5 % default.
    if ratio and float(ratio) > 0:
        return IDLE_RATIO_MULTIPLIER * float(ratio), source
    if ratio is not None:
        source = f"{source} w/T=0 -> default"
    else:
        source = "default R=5%"
    return IDLE_RATIO_DEFAULT, source


def tank_idle(run):
    samples = _samples(run)
    tanks = _tanks(run)
    if not run.tank_state or not samples:
        return {"id": "tank_idle", "title": "虫王空闲", "status": "N/A",
                "reason": "missing engine/tank_state.jsonl (run predates the 250 ms tank timeline)",
                "cap": TANK_IDLE["cap"], "raw": 0.0, "detail": {"windows": []}}
    if not tanks:
        return {"id": "tank_idle", "title": "虫王空闲", "status": "N/A",
                "reason": "no tanks in meta", "cap": TANK_IDLE["cap"], "raw": 0.0, "detail": {"windows": []}}
    end_ms = float(run.result.get("gameMs") or 0)
    begin_ms = _begin_ms(run)
    if end_ms <= begin_ms:
        return {"id": "tank_idle", "title": "虫王空闲", "status": "N/A",
                "reason": "task timeline is empty", "cap": TANK_IDLE["cap"], "raw": 0.0, "detail": {"windows": []}}
    windows, alive = [], {}
    bay_full = _bay_full_intervals(samples, begin_ms, end_ms)
    for tank in tanks:
        rows = samples.get(tank["id"]) or []
        if not rows:
            continue
        death = _death_ms(run, tank["id"])
        unit_end = min(end_ms, death) if death is not None else end_ms
        start = max(begin_ms, rows[0]["ms"])
        alive[tank["id"]] = max(0.0, (unit_end - start) / 1000.0)
        for window in _unit_windows(rows, begin_ms, unit_end, bay_full,
                                    drop_tail=DROP_TAIL and death is None):
            windows.append({"unitId": tank["id"], "alias": tank.get("alias"), **window})
    skipped_begin = skipped_tail = 0
    if DROP_BEGIN:
        kept = []
        for window in windows:
            if window["start"] <= begin_ms:
                skipped_begin += 1
            else:
                kept.append(window)
        windows = kept
    if DROP_TAIL:
        kept = []
        for window in windows:
            if window["end"] >= end_ms:
                skipped_tail += 1
            else:
                kept.append(window)
        windows = kept
    total_seconds = sum(alive.values())
    reference, source = _idle_reference(run)
    if not windows:
        return {"id": "tank_idle", "title": "虫王空闲", "status": "OK", "cap": TANK_IDLE["cap"], "raw": 0.0,
                "detail": {"windows": [], "beginGameMs": round(begin_ms, 1),
                           "aliveSeconds": round(total_seconds, 3),
                           "aliveByUnit": {str(key): round1(value) for key, value in alive.items()},
                           "weightedSeconds": 0.0, "ratio": 0.0,
                           "bayFullIntervals": [[round(a, 1), round(b, 1)] for a, b in bay_full],
                           "R": round(reference, 4), "RSource": source,
                           "skippedBegin": skipped_begin, "skippedTail": skipped_tail,
                           "weights": IDLE_WEIGHTS, "minimumSeconds": IDLE_MIN_SECONDS,
                           "samplingMs": 250,
                           "formula": f"{IDLE_SCALE:g}*(w/T)/R, w = sum((A-3)*1.5) + sum((B-8)*2)"}}
    rows, weighted = [], 0.0
    for window in windows:
        seconds = (window["end"] - window["start"]) / 1000.0
        weight = IDLE_WEIGHTS[window["kind"]]
        minimum = IDLE_MIN_SECONDS[window["kind"]]
        over = max(0.0, seconds - minimum)
        counted = over > 0.0
        points = over * weight
        weighted += points
        rows.append({"unitId": window["unitId"], "alias": window.get("alias"), "kind": window["kind"],
                     "startMs": round(window["start"], 1), "endMs": round(window["end"], 1),
                     "seconds": round(seconds, 3), "weight": weight,
                     "minimumSeconds": minimum, "counted": counted,
                     "points": round1(points)})
    ratio = weighted / total_seconds if total_seconds > 0 else None
    raw = IDLE_SCALE * ratio / reference if ratio is not None and reference > 0 else 0.0
    return {"id": "tank_idle", "title": "虫王空闲", "status": "OK", "cap": TANK_IDLE["cap"], "raw": raw,
            "detail": {"windows": rows, "beginGameMs": round(begin_ms, 1),
                       "aliveSeconds": round(total_seconds, 3),
                       "aliveByUnit": {str(key): round1(value) for key, value in alive.items()},
                       "weightedSeconds": round(weighted, 3),
                       "ratio": None if ratio is None else round(ratio, 4),
                       "bayFullIntervals": [[round(a, 1), round(b, 1)] for a, b in bay_full],
                       "R": round(reference, 4), "RSource": source,
                       "skippedBegin": skipped_begin, "skippedTail": skipped_tail,
                       "weights": IDLE_WEIGHTS, "minimumSeconds": IDLE_MIN_SECONDS,
                       "samplingMs": 250,
                       "formula": f"{IDLE_SCALE:g}*(w/T)/R, w = sum((A-3)*1.5) + sum((B-8)*2)"}}


def _baseline_seconds(run):
    table = _baselines()
    # Baselines are per type, not per task/level: level>1 shares its type's T.
    seconds = (table.get("byType") or {}).get(str(run.meta.get("type")))
    source = "per-type baseline"
    if not seconds:
        limit = float((run.meta.get("limits") or {}).get("gameSeconds") or 0.0)
        if limit:
            seconds = 0.55 * limit
            source = "0.55 x game limit"
    return seconds, source


def duration_score(run, begin_ms=None):
    end = run.result.get("gameMs")
    if end is None:
        return {"id": "duration", "title": "整体时长", "status": "N/A", "reason": "missing result.gameMs",
                "cap": DURATION["cap"], "raw": 0.0, "detail": {}}
    end_ms = float(end)
    start_ms = float(begin_ms or 0.0)
    duration_s = max(0.0, (end_ms - start_ms) / 1000.0)
    seconds, source = _baseline_seconds(run)
    if not seconds:
        return {"id": "duration", "title": "整体时长", "status": "N/A", "reason": "no baseline duration",
                "cap": DURATION["cap"], "raw": 0.0, "detail": {"durationSeconds": round(duration_s, 3)}}
    low, high = DURATION_LOWER_RATIO * float(seconds), DURATION_UPPER_RATIO * float(seconds)
    if duration_s < low:
        points = DURATION["cap"] * (1.0 - (duration_s / low) ** 2) if low > 0 else DURATION["cap"]
    elif duration_s > high:
        points = DURATION["cap"]
    elif DURATION_QUADRATIC_SPACE == "normalized":
        points = curve((duration_s - low) / (high - low), 0.0, 1.0, 0.0, DURATION["cap"], "quadratic", QUADRATIC_A)
    elif DURATION_QUADRATIC_SPACE == "minutes":
        points = curve(duration_s / 60.0, low / 60.0, high / 60.0, 0.0, DURATION["cap"], "quadratic", QUADRATIC_A)
    else:
        points = curve(duration_s, low, high, 0.0, DURATION["cap"], "quadratic", QUADRATIC_A)
    return {"id": "duration", "title": "整体时长", "status": "OK", "cap": DURATION["cap"], "raw": cap(points, DURATION["cap"]),
            "detail": {"durationSeconds": round(duration_s, 3), "endGameMs": round(end_ms, 1),
                       "startGameMs": round(start_ms, 1), "baselineSeconds": round(float(seconds), 3),
                       "baselineSource": source, "ratio": round(duration_s / float(seconds), 3),
                       "lowerRatio": DURATION_LOWER_RATIO, "upperRatio": DURATION_UPPER_RATIO,
                       "rangeSeconds": [round(low, 1), round(high, 1)], "quadraticA": QUADRATIC_A,
                       "quadraticSpace": DURATION_QUADRATIC_SPACE}}


def compute(run):
    begin_ms = _begin_ms(run)
    entries = [tank_loss(run), tank_idle(run), duration_score(run, begin_ms)]
    notes = ["每一项独立封顶后求和；缺证据的项记 N/A 且不扣分。",
             "虫王空闲来自引擎 250 game-ms 的 tank_state 时间线：就绪 = 在维修湾范围内 + idle，"
             "且该时刻湾内所有坦克的 HP 都满；滞留 = 不在任何维修湾范围内 + idle，不看 HP；"
             "阈值分别 >3s / >8s；开头为 t=0、末尾到 end 的窗口丢弃。",
             "湾内全员满血按采样时刻逐帧求交集；只要有一辆在湾内未满，湾内任何坦克都不算就绪。",
             "2026-11-12 起 CASE4 主体是虫王 bugMeleeT31（内置自定义单位，无护盾）；评分不读护盾字段。",
             "R 默认 5%；config.json 的 duration.idleRatioByType 有该 type 的基线 w/T 时取 5 倍基线。",
             f"整体时长区间 [{DURATION_LOWER_RATIO:g}T,{DURATION_UPPER_RATIO:g}T]，"
             f"横坐标取 {DURATION_QUADRATIC_SPACE}；低于下限按 30*(1-(x/lower)^2) 计。"]
    diagnostics = [{"severity": "info", "reason": item["reason"]} for item in entries if item["status"] != "OK"]
    return document(VERSION, BASELINE, entries, notes, diagnostics)
