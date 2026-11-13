"""CASE2-LTE deduction score — the executable form of `score_design.md` (case2-score-v1).

Three separate deductions, each capped, then `100 - sum`:

1. **行动延迟 (cap 50)** — for every build/upgrade instruction that actually took effect, walk
   backwards from its apply moment `B` while the team balance covers its cost and the acting
   builder/building was idle. For each non-zero-start window of `d` seconds,
   `w = weightMax * (min(d,maxSeconds)/maxSeconds)^exponent`; `K = sum(w)/count`,
   `S = K*scale`.
2. **无关行为 (cap 30)** — violations ×4, replaced/cancelled/failed/timed-out B instructions ×2.5,
   completed builds/upgrades beyond the target composition ×1.
3. **底层命令执行间隔 (cap 50)** — the series is the spacing between adjacent native commands;
   `S = meanWeight*f(trimmed mean) + outlierWeight*min(100, sum(P(outlier - mean)))`, where
   `f(x)=100*((clamp(x,20,60)-20)/40)^0.9` and
   `P(d)=100*((clamp(d,25,120)-25)/95)^2`.

Every number is derived from one run directory; nothing is invented when evidence is missing
(that item then scores 0 with `status="N/A"` and a reason).
"""
from __future__ import annotations
import bisect
import re
from pathlib import Path
import sys

CASE = Path(__file__).resolve().parent
sys.path.insert(0, str(CASE.parent))
from common.config import evaluation  # noqa: E402
from common.scoring import cap, document, round1, split_outliers  # noqa: E402

_EVALUATION = evaluation(CASE)
VERSION = _EVALUATION["scoreVersion"]
BASELINE = _EVALUATION.get("scoreBaseline", 100)
TERMINALS = ("completed", "failed", "cancelled", "superseded", "timeout", "rejected")
# One nominal income tick is 40 ticks x 16 game-ms = 0.64 s, so a rate of R (credits per nominal
# tick) is R * 1000/640 credits per game second. METRICS.md 4.4 derives the same 12.5/18.75/31.25.
INCOME_SCALE = 1000.0 / 640.0
WEIGHTS = _EVALUATION["irrelevant"]["weights"]
IRRELEVANT_CAP = _EVALUATION["irrelevant"]["cap"]
ACTION_DELAY = _EVALUATION["actionDelay"]
DELAY_WEIGHT_MAX = float(ACTION_DELAY.get("weightMax", 4))
DELAY_MAX_SECONDS = float(ACTION_DELAY.get("maxSeconds", 45))
DELAY_EXPONENT = float(ACTION_DELAY.get("exponent", 1.5))
CADENCE = _EVALUATION["cadence"]
CADENCE_MEAN_EXPONENT = float(CADENCE.get("meanExponent", 0.9))
CADENCE_OUTLIER_EXPONENT = float(CADENCE.get("outlierExponent", 2.0))
CADENCE_ANOMALY_CAP = float(CADENCE.get("anomalyCap", 100))


def _power_curve(value, endpoints, exponent):
    """`100 * ((clamp(x,lo,hi)-lo)/(hi-lo))^p`, clamped to [0,100]."""
    lo, hi = (float(endpoints[0]), float(endpoints[1]))
    if hi <= lo:
        return 0.0
    bounded = min(max(float(value), lo), hi)
    return min(100.0, max(0.0, 100.0 * ((bounded - lo) / (hi - lo)) ** exponent))


def _delay_weight(seconds):
    """`weightMax * (min(d,maxSeconds)/maxSeconds)^exponent`; a non-positive window is 0."""
    if DELAY_MAX_SECONDS <= 0:
        return DELAY_WEIGHT_MAX
    bounded = min(max(0.0, float(seconds)), DELAY_MAX_SECONDS)
    return DELAY_WEIGHT_MAX * (bounded / DELAY_MAX_SECONDS) ** DELAY_EXPONENT


def _instruction_rows(run):
    """One row per B request, with its lifecycle events and the moments the score needs."""
    grouped = {}
    for event in run.events:
        if event.get("kind") == "instruction":
            grouped.setdefault(event.get("requestId"), []).append(event)
    incomes = [e for e in run.events if e.get("kind") == "income"]
    rates = sorted((e["gameMs"], float(e.get("incomePerSecond") or 0.0)) for e in incomes)
    rows = []
    for request in run.gateway:
        if request.get("class") != "B":
            continue
        events = grouped.get(request.get("seq"), [])
        terminal = next((e for e in events if e["event"] in TERMINALS), None)
        started = next((e for e in events if e["event"] == "order_started"), None)
        accepted = next((e for e in events if e["event"] == "accepted" and e.get("operation")), None)
        paid = next((e for e in events if (e.get("actualCost") or 0) > 0), None)
        operation = (accepted or terminal or started or {}).get("operation")
        cost = (accepted or started or {}).get("cost")
        if cost is None:
            cost = _cost_from_meta(run, operation, (accepted or terminal or {}).get("targetLevel"))
        rows.append({
            "requestId": request.get("seq"), "status": request.get("status"), "operation": operation,
            "actor": (accepted or terminal or started or {}).get("actor"),
            "buildingId": (terminal or accepted or {}).get("buildingId"),
            "targetLevel": (terminal or accepted or {}).get("targetLevel"),
            "cost": cost, "acceptedMs": _ms(accepted), "appliedMs": _ms(started),
            "terminalMs": _ms(terminal), "terminal": terminal["event"] if terminal else "unresolved",
            "creditsAtApply": (started or accepted or {}).get("credits"),
            "paidMs": _ms(paid), "actualCost": next((e.get("actualCost") for e in events if (e.get("actualCost") or 0) > 0), None),
            "events": events, "rates": rates,
        })
    return rows


def _ms(event):
    return float(event["gameMs"]) if event and event.get("gameMs") is not None else None


def _cost_from_meta(run, operation, target_level):
    """Fallback when the lifecycle row predates the `cost` field."""
    economy = run.meta.get("economy") or []
    if operation == "build" and economy:
        return economy[0].get("buildCost")
    if operation == "upgrade" and target_level:
        level = int(target_level) - 2
        if 0 <= level < len(economy):
            return economy[level].get("upgradeCost")
    return None


class Credits:
    """Piecewise credit curve: exact values at evidence anchors, linear income in between."""

    def __init__(self, points, rate_at):
        self.points = sorted(points)
        self.times = [p[0] for p in self.points]
        self.rate_at = rate_at

    def rate(self, ms):
        return self.rate_at(ms)

    def earliest(self, end_ms, cost):
        """Earliest moment from which the balance covered `cost` up to `end_ms` (0 if never short).

        Only anchors strictly before `end_ms` are considered: the instruction's own payment happens
        at (or just after) its apply moment and must not make its own window look zero-length.
        """
        index = bisect.bisect_left(self.times, end_ms) - 1
        for k in range(index, -1, -1):
            start, value = self.points[k]
            if value >= cost:
                continue
            rate = self.rate(start)
            if rate <= 0:
                return start
            return min(end_ms, start + (cost - value) / rate)
        return 0.0


def _credit_curve(run, rows):
    """Anchors from the recorded `credits` field; otherwise rebuilt from costs and income."""
    initial = float(run.meta.get("initialCredits") or 0.0)
    anchors = {}
    for row in rows:
        for event in row["events"]:
            if event.get("credits") is not None:
                moment = float(event["gameMs"])
                anchors[moment] = min(anchors.get(moment, float(event["credits"])), float(event["credits"]))
    rates = rows[0]["rates"] if rows else []

    def rate_at(ms):
        value = 0.0
        for moment, rate in rates:
            if moment <= ms:
                value = rate
            else:
                break
        return value * INCOME_SCALE / 1000.0

    if anchors:
        anchors.setdefault(0.0, initial)
        return Credits(sorted(anchors.items()), rate_at), "recorded credits"
    # Fallback: initial balance, income accrual between spends, then each real deduction.
    spends = sorted((row["paidMs"], float(row["cost"])) for row in rows
                    if row["paidMs"] is not None and row["cost"])
    points, balance, previous = [(0.0, initial)], initial, 0.0
    for moment, cost in spends:
        balance += _income_between(rates, previous, moment) - cost
        previous = moment
        points.append((moment, balance))
    return Credits(points, rate_at), "rebuilt from costs + income anchors"


def _nominal_rate(rates, ms):
    value = 0.0
    for moment, rate in rates:
        if moment <= ms:
            value = rate
        else:
            break
    return value


def _income_between(rates, start, end):
    """Credits earned in (start, end], using the rate in effect on each sub-interval."""
    total, previous = 0.0, start
    for moment, _ in rates:
        if moment <= previous:
            continue
        if moment >= end:
            break
        total += _nominal_rate(rates, previous) * INCOME_SCALE * (moment - previous) / 1000.0
        previous = moment
    if previous < end:
        total += _nominal_rate(rates, previous) * INCOME_SCALE * (end - previous) / 1000.0
    return total


def _actor_free_ms(rows, actor, moment):
    """When the acting builder/building last became idle before `moment` (its own order excluded)."""
    free = 0.0
    # An upgrade actor (a building) does not exist before its build completed. The build row is
    # recorded on the builder, so without this the first upgrade window starts at t=0 and is
    # overestimated by the whole construction time.
    for row in rows:
        if row["operation"] == "build" and row["buildingId"] == actor and row["terminalMs"] is not None:
            if row["terminalMs"] < moment:
                free = max(free, row["terminalMs"])
    for row in rows:
        if row["actor"] != actor or row["appliedMs"] is None or row["requestId"] is None:
            continue
        if row["appliedMs"] >= moment:
            continue
        end = row["terminalMs"] if row["terminalMs"] is not None else moment
        free = max(free, min(end, moment))
    return free


def action_delay(run, rows):
    effective = [row for row in rows if row["appliedMs"] is not None and row["status"] == "submitted"]
    if not effective:
        return {"id": "action_delay", "title": "行动延迟", "status": "N/A", "reason": "no applied build/upgrade instruction",
                "cap": ACTION_DELAY["cap"], "raw": 0.0, "detail": {"windows": []}}
    curve_model, source = _credit_curve(run, rows)
    builder = (run.meta.get("builder") or {}).get("id") if isinstance(run.meta.get("builder"), dict) else run.meta.get("builder")
    builder = builder or 1000
    windows, skipped = [], 0
    detail = []
    for row in effective:
        cost = row["cost"]
        if not cost:
            detail.append({"requestId": row["requestId"], "skipped": "missing cost"})
            continue
        end = row["appliedMs"]
        funding = curve_model.earliest(end, float(cost))
        actor = builder if row["operation"] == "build" else (row["buildingId"] or row["actor"])
        idle = _actor_free_ms(rows, actor, end)
        start = max(0.0, funding, idle)
        seconds = max(0.0, (end - start) / 1000.0)
        entry = {"requestId": row["requestId"], "operation": row["operation"], "actor": actor,
                 "cost": cost, "applyGameMs": end, "startGameMs": round(start, 1),
                 "refillGameMs": round(funding, 1), "actorFreeGameMs": round(idle, 1),
                 "windowSeconds": round(seconds, 3), "creditsAtApply": row["creditsAtApply"]}
        if start <= 0.0:
            entry["skipped"] = "zero_start"
            skipped += 1
            detail.append(entry)
            continue
        entry["weight"] = round(_delay_weight(seconds), 3)
        windows.append(entry)
        detail.append(entry)
    if not windows:
        return {"id": "action_delay", "title": "行动延迟", "status": "N/A",
                "reason": "no non-zero-start delay window", "cap": ACTION_DELAY["cap"], "raw": 0.0,
                "detail": {"windows": [], "instructions": detail, "creditSource": source,
                           "skippedZeroStart": skipped}}
    weight_sum = sum(entry["weight"] for entry in windows)
    coefficient = weight_sum / len(windows)
    raw = max(0.0, coefficient * ACTION_DELAY["scale"])
    return {"id": "action_delay", "title": "行动延迟", "status": "OK", "cap": ACTION_DELAY["cap"],
            "raw": round(raw, 3),
            "detail": {"coefficient": round(coefficient, 3), "weightSum": round(weight_sum, 3),
                       "count": len(windows), "skippedZeroStart": skipped,
                       "weightMax": DELAY_WEIGHT_MAX, "maxSeconds": DELAY_MAX_SECONDS,
                       "exponent": DELAY_EXPONENT, "scale": ACTION_DELAY["scale"],
                       "windows": [entry["windowSeconds"] for entry in windows],
                       "windowRows": windows, "creditSource": source, "instructions": detail,
                       "formula": f"K=sum({DELAY_WEIGHT_MAX:g}*(min(d,{DELAY_MAX_SECONDS:g})/{DELAY_MAX_SECONDS:g})^{DELAY_EXPONENT:g})/cnt; S=K*{ACTION_DELAY['scale']:g}; zero-start windows skipped"}}


def _planned_levels(meta):
    text = str(meta.get("targetComposition") or "")
    levels = []
    for part in text.split("+"):
        match = re.search(r"(\d+)\s*[xX×]\s*T(\d)", part.strip())
        if match:
            levels.extend([int(match.group(2))] * int(match.group(1)))
    return levels


def irrelevant(run, rows):
    violations = len(run.violations or [])
    end_ms = run.result.get("gameMs")
    # An instruction cut off by the end of the run (LteSession.finish cancels what is still active)
    # was not a wasted decision, so it is not counted here.
    wasted = [row for row in rows if row["terminal"] in {"superseded", "cancelled", "failed", "timeout"}
              and not (end_ms is not None and row["terminalMs"] is not None and row["terminalMs"] >= end_ms - 16)]
    levels = _planned_levels(run.meta)
    completed = [row for row in rows if row["terminal"] == "completed"]
    if levels:
        planned_builds = len(levels)
        planned = {2: sum(1 for level in levels if level >= 2), 3: sum(1 for level in levels if level >= 3)}
        actual = {1: sum(1 for row in completed if row["operation"] == "build"),
                  2: sum(1 for row in completed if row["operation"] == "upgrade" and row["targetLevel"] == 2),
                  3: sum(1 for row in completed if row["operation"] == "upgrade" and row["targetLevel"] == 3)}
        surplus = max(0, actual[1] - planned_builds) + sum(max(0, actual[level] - planned[level]) for level in (2, 3))
        surplus_detail = {"plannedLevels": levels, "actual": actual,
                          "planned": {"builds": planned_builds, **{str(k): v for k, v in planned.items()}}}
    else:
        surplus, surplus_detail = 0, {"reason": "targetComposition is not a countable composition"}
    points = violations * WEIGHTS["violation"] + len(wasted) * WEIGHTS["wasted"] + surplus * WEIGHTS["surplus"]
    return {"id": "irrelevant", "title": "无关行为", "status": "OK", "cap": IRRELEVANT_CAP, "raw": points,
            "detail": {"counts": {"violation": violations, "wasted": len(wasted), "surplus": surplus},
                       "weights": WEIGHTS,
                       "rows": [{"requestId": row["requestId"], "terminal": row["terminal"], "kind": "wasted"} for row in wasted],
                       "violations": [{"violationType": v.get("violationType"), "reason": v.get("reason")} for v in run.violations or []],
                       "composition": surplus_detail}}


def cadence(run):
    natives = sorted((float(e["gameMs"]) for e in run.events if e.get("kind") == "native" and e.get("gameMs") is not None))
    intervals = [(after - before) / 1000.0 for before, after in zip(natives, natives[1:])]
    if not intervals:
        return {"id": "cadence", "title": "底层命令执行间隔", "status": "N/A", "reason": "fewer than two native commands",
                "cap": CADENCE["cap"], "raw": 0.0, "detail": {"intervals": []}}
    kept, outliers, cutoff = split_outliers(intervals)
    mean = sum(kept) / len(kept)
    overall = _power_curve(mean, CADENCE["meanSeconds"], CADENCE_MEAN_EXPONENT)
    reactions = []
    for value in outliers:
        delta = max(0.0, value - mean)
        reactions.append({"intervalSeconds": round(value, 3), "deltaSeconds": round(delta, 3),
                          "points": round(_power_curve(delta, CADENCE["outlierSeconds"],
                                                       CADENCE_OUTLIER_EXPONENT), 3)})
    anomaly = min(CADENCE_ANOMALY_CAP, sum(item["points"] for item in reactions))
    mean_part = overall * CADENCE["meanWeight"]
    anomaly_part = anomaly * CADENCE["outlierWeight"]
    points = round(cap(mean_part + anomaly_part, CADENCE["cap"]), 3)
    return {"id": "cadence", "title": "底层命令执行间隔", "status": "OK", "cap": CADENCE["cap"], "raw": points,
            "detail": {"intervals": [round(v, 3) for v in intervals], "trimmedMeanSeconds": round(mean, 3),
                       "outlierCutoffSeconds": None if cutoff is None else round(cutoff, 3),
                       "overallRhythm": round(overall, 3), "anomalyReaction": round(anomaly, 3),
                       "meanPart": round(mean_part, 3), "anomalyPart": round(anomaly_part, 3),
                       "outliers": reactions, "nativeCommands": len(natives),
                       "meanExponent": CADENCE_MEAN_EXPONENT, "outlierExponent": CADENCE_OUTLIER_EXPONENT,
                       "anomalyCap": CADENCE_ANOMALY_CAP,
                       "formula": f"{CADENCE['meanWeight']:g}*100*((clamp(mean,{CADENCE['meanSeconds'][0]},{CADENCE['meanSeconds'][1]})-{CADENCE['meanSeconds'][0]})/{CADENCE['meanSeconds'][1]-CADENCE['meanSeconds'][0]})^{CADENCE_MEAN_EXPONENT:g} + {CADENCE['outlierWeight']:g}*min({CADENCE_ANOMALY_CAP:g},sum(100*((clamp(delta,{CADENCE['outlierSeconds'][0]},{CADENCE['outlierSeconds'][1]})-{CADENCE['outlierSeconds'][0]})/{CADENCE['outlierSeconds'][1]-CADENCE['outlierSeconds'][0]})^{CADENCE_OUTLIER_EXPONENT:g})), cap {CADENCE['cap']:g}"}}


def compute(run):
    rows = _instruction_rows(run)
    entries = [action_delay(run, rows), irrelevant(run, rows), cadence(run)]
    notes = ["每一项独立封顶后求和；缺证据的项记 N/A 且不扣分。",
             "行动延迟：K=sum(weightMax*(min(d,maxSeconds)/maxSeconds)^exponent)/cnt，"
             "S=K*scale；start=0 的窗口忽略。",
             "cadence 的序列是相邻底层命令的间隔（秒）。"]
    diagnostics = [{"severity": "info", "reason": item["reason"]} for item in entries if item["status"] != "OK"]
    return document(VERSION, BASELINE, entries, notes, diagnostics)
