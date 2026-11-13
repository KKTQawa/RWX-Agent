"""CASE3-Transport deduction score — the executable form of `score_design.md` (case3-score-v1).

Five separate deductions, each capped, then `100 - sum`:

1. **行动延迟 (cap 40)** — for every production order that took effect, walk backwards from the
   accepted moment `B` while the team balance covers the unit's cost *and* the factory had already
   finished its previous order; `w(d)=weightMax*(min(d,maxSeconds)/maxSeconds)^exponent`,
   `K=sum(w)/cnt` (start/end windows are ignored but still counted in `cnt`), `S=K*scale`.
2. **无关行为 (cap 20)** — violations ×7.5, failed/invalid requests ×4.5, and non-return empty
   moves or empty unloads ×1.8.
3. **运输机损失 (cap 15)** — `(1-K1)*5 + K2*15`, where K1 is the surviving HP share over all
   transports and K2 the destroyed share.
4. **运输机空闲 (cap 0, temporarily disabled)** — ground windows before takeoff and after landing,
   scored `15*f(seconds)` each with `f:<3s 0, [3,25] exp{0,0.8}, (25,40) linear{0.8,1}, >=40s 1`.
5. **整体时长 (cap 60)** — below `0.8T` the penalty is `60*(1-(x/0.8T)^2)`; inside
   `[0.8T,3T]` it is the `a=-3` quadratic through `(0.8T,0)` and `(3T,60)`; above `3T` it is 60.
   `T` is the measured baseline for this task when one exists, otherwise the per-type default.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys

CASE = Path(__file__).resolve().parent
sys.path.insert(0, str(CASE.parent))
from common.config import evaluation  # noqa: E402
from common.scoring import cap, curve, document, piecewise, round1  # noqa: E402

_EVALUATION = evaluation(CASE)
VERSION = _EVALUATION["scoreVersion"]
BASELINE = _EVALUATION.get("scoreBaseline", 100)
INCOME_SCALE = 1000.0 / 640.0   # one nominal income tick = 40 ticks x 16 game-ms
WEIGHTS = _EVALUATION["irrelevant"]["weights"]
IRRELEVANT_CAP = _EVALUATION["irrelevant"]["cap"]
DECOY_DAMAGE = _EVALUATION["irrelevant"].get("decoyDamage", True)
ACTION_DELAY = _EVALUATION["actionDelay"]
ACTION_WEIGHT_MAX = float(ACTION_DELAY.get("weightMax", 4))
ACTION_MAX_SECONDS = float(ACTION_DELAY.get("maxSeconds", 60))
ACTION_EXPONENT = float(ACTION_DELAY.get("exponent", 2.0))
TRANSPORT_LOSS = _EVALUATION["transportLoss"]
TRANSPORT_IDLE = _EVALUATION["transportIdle"]
IDLE_POINTS = TRANSPORT_IDLE["points"]
EXCLUDE_LOADED_READY = TRANSPORT_IDLE.get("excludeLoadedReady", True)
EXCLUDE_DECOY_SORTIES = TRANSPORT_IDLE.get("excludeDecoySorties", True)
IDLE_SEGMENTS = tuple(tuple(segment) for segment in TRANSPORT_IDLE["segments"])
DURATION = _EVALUATION["duration"]
QUADRATIC_A = DURATION["quadraticA"]
DURATION_LOWER_RATIO = float(DURATION.get("lowerRatio", 0.8))
DURATION_UPPER_RATIO = float(DURATION.get("upperRatio", 3.0))
# Coordinate scale for the duration quadratic. `raw` is the project convention
# (evaluate/scoring-curves.js); `normalized` maps [lowerRatio*T, upperRatio*T] to [0,1]
# and `minutes` rescales x.
DURATION_QUADRATIC_SPACE = DURATION["quadraticSpace"]


def _rows(run):
    production = run.production
    orders, started = [], {}
    for row in production:
        if row.get("kind") != "order":
            continue
        if row.get("event") == "accepted":
            orders.append(row)
        elif row.get("event") == "started":
            started[row.get("requestId")] = row
    moves = run.moves()
    unloads = run.unloads()
    return orders, started, moves, unloads


class Credits:
    """Constant-income model anchored at the real order costs (CASE3 extractors never change)."""

    def __init__(self, initial, rate_per_ms, spends):
        self.points = [(0.0, float(initial))]
        balance = float(initial)
        previous = 0.0
        for moment, cost in spends:
            balance += rate_per_ms * (moment - previous) - cost
            previous = moment
            self.points.append((moment, balance))
        self.rate_per_ms = rate_per_ms

    def earliest(self, end_ms, cost):
        index = len(self.points) - 1
        while index > 0 and self.points[index][0] >= end_ms:
            index -= 1
        for k in range(index, -1, -1):
            start, value = self.points[k]
            if value >= cost:
                continue
            if self.rate_per_ms <= 0:
                return start
            return min(end_ms, start + (cost - value) / self.rate_per_ms)
        return 0.0


def _factory_free(production, factory_id, moment, request_id):
    """When the factory's previous order actually finished (identity-tracked `finished` rows)."""
    free = 0.0
    for row in production:
        if row.get("kind") != "order" or row.get("event") != "finished":
            continue
        if row.get("factoryId") != factory_id or row.get("requestId") == request_id:
            continue
        when = row.get("gameMs")
        if when is not None and when <= moment:
            free = max(free, float(when))
    return free


def _action_weight(seconds):
    """`weightMax * (min(d,maxSeconds)/maxSeconds)^exponent`; non-positive is 0."""
    if ACTION_MAX_SECONDS <= 0:
        return ACTION_WEIGHT_MAX
    bounded = min(max(0.0, float(seconds)), ACTION_MAX_SECONDS)
    return ACTION_WEIGHT_MAX * (bounded / ACTION_MAX_SECONDS) ** ACTION_EXPONENT


def action_delay(run, orders, started):
    effective = [row for row in orders if row.get("cost") is not None and row.get("gameMs") is not None]
    if not effective:
        return {"id": "action_delay", "title": "行动延迟", "status": "N/A",
                "reason": "orders carry no cost/credits evidence", "cap": ACTION_DELAY["cap"], "raw": 0.0,
                "detail": {"windows": []}}
    rate = float(run.result.get("incomePerSecond") or 0.0) * INCOME_SCALE / 1000.0
    spends = sorted((float(started[row["requestId"]]["gameMs"]), float(row["cost"]))
                    for row in orders if row.get("requestId") in started and row.get("cost") is not None)
    model = Credits(run.meta.get("initialCredits") or 0.0, rate, spends)
    windows, detail = [], []
    skipped_start = skipped_end = 0
    total_count = len(effective)
    end_ms = float(run.result.get("gameMs") or 0.0)
    for row in effective:
        cost = float(row["cost"])
        end = float(row["gameMs"])
        funding = model.earliest(end, cost)
        busy = _factory_free(run.production, row.get("factoryId"), end, row.get("requestId"))
        start = max(0.0, funding, busy)
        seconds = max(0.0, (end - start) / 1000.0)
        begun = started.get(row.get("requestId"))
        entry = {"requestId": row.get("requestId"), "factoryId": row.get("factoryId"),
                 "unitType": row.get("unitType"), "cost": cost, "acceptedGameMs": end,
                 "startGameMs": round(start, 1),
                 "startedGameMs": None if not begun else begun.get("gameMs"),
                 "queueWaitMs": None if not begun else round1(begun.get("gameMs") - end),
                 "refillGameMs": round(funding, 1), "factoryFreeGameMs": round(busy, 1),
                 "windowSeconds": round(seconds, 3)}
        if start <= 0.0:
            entry["skipped"] = "zero_start"
            skipped_start += 1
            detail.append(entry)
            continue
        if end_ms > 0 and end >= end_ms:
            entry["skipped"] = "end_of_run"
            skipped_end += 1
            detail.append(entry)
            continue
        entry["weight"] = round(_action_weight(seconds), 3)
        windows.append(seconds)
        detail.append(entry)
    weight_sum = sum(_action_weight(seconds) for seconds in windows)
    # The draft explicitly says cnt includes the start/end windows even though they are ignored.
    coefficient = weight_sum / total_count if total_count else 0.0
    raw = max(0.0, coefficient * ACTION_DELAY["scale"])
    return {"id": "action_delay", "title": "行动延迟", "status": "OK", "cap": ACTION_DELAY["cap"],
            "raw": round(raw, 3),
            "detail": {"coefficient": round(coefficient, 3), "weightSum": round(weight_sum, 3),
                       "count": len(windows), "totalCount": total_count,
                       "skippedZeroStart": skipped_start, "skippedEnd": skipped_end,
                       "weightMax": ACTION_WEIGHT_MAX, "maxSeconds": ACTION_MAX_SECONDS,
                       "exponent": ACTION_EXPONENT, "scale": ACTION_DELAY["scale"],
                       "windows": [round(value, 3) for value in windows], "orders": detail,
                       "incomePerSecond": run.result.get("incomePerSecond"),
                       "creditsPerSecond": round(rate * 1000.0, 3),
                       "formula": f"K=sum({ACTION_WEIGHT_MAX:g}*(min(d,{ACTION_MAX_SECONDS:g})/{ACTION_MAX_SECONDS:g})^{ACTION_EXPONENT:g})/cnt; S=K*{ACTION_DELAY['scale']:g}; start/end windows ignored, cnt includes them"}}


def _base_bounds(run):
    meta = run.meta
    size = int(meta.get("mapSize") or 0)
    tile = float(meta.get("tileSize") or 20)
    tiles = meta.get("baseIslandTiles") or []
    if not size or not tiles:
        return None
    xs = [index % size for index in tiles]
    ys = [index // size for index in tiles]
    return (min(xs) * tile, min(ys) * tile, (max(xs) + 1) * tile, (max(ys) + 1) * tile)


def _empty_at(run, transport_id, moment):
    carried = []
    for when, cargo in run.cargo_timeline(transport_id):
        if when is not None and when <= moment:
            carried = cargo
        else:
            break
    return not carried


def irrelevant(run, moves, unloads):
    violations = len(run.violations or [])
    # Only actionable (B) failures count: a rejected probe of the world is an observation, not a task action.
    failed = [row for row in run.gateway if row.get("class") == "B" and row.get("status") in {"invalid_request", "error"}]
    bounds = _base_bounds(run)
    damage = {}
    for row in run.transport or []:
        if row.get("kind") == "damage" and row.get("transportId") is not None and row.get("gameMs") is not None:
            damage.setdefault(row["transportId"], []).append(float(row["gameMs"]))
    empty_moves, decoy_moves, empty_unloads = [], [], []
    for row in moves:
        transport_id = row.get("transportId")
        moment = row.get("gameMs") or 0
        if not _empty_at(run, transport_id, moment):
            continue
        # An empty sortie that draws anti-air fire is a decoy/reconnaissance flight, not waste.
        if DECOY_DAMAGE and any(hit >= moment for hit in damage.get(transport_id, [])):
            decoy_moves.append({"transportId": transport_id, "gameMs": moment,
                                "x": row.get("x"), "y": row.get("y")})
            continue
        destination = (row.get("x"), row.get("y"))
        returning = bounds is not None and destination[0] is not None and \
            bounds[0] - 20 <= destination[0] <= bounds[2] + 20 and bounds[1] - 20 <= destination[1] <= bounds[3] + 20
        if not returning:
            empty_moves.append({"transportId": transport_id, "gameMs": moment, "x": destination[0], "y": destination[1]})
    for row in unloads:
        if _empty_at(run, row.get("transportId"), row.get("gameMs") or 0):
            empty_unloads.append({"transportId": row.get("transportId"), "gameMs": row.get("gameMs")})
    points = (violations * WEIGHTS["violation"] + len(failed) * WEIGHTS["failed"]
              + (len(empty_moves) + len(empty_unloads)) * WEIGHTS["waste"])
    return {"id": "irrelevant", "title": "无关行为", "status": "OK", "cap": IRRELEVANT_CAP, "raw": points,
            "detail": {"counts": {"violation": violations, "failed": len(failed),
                                  "emptyMove": len(empty_moves), "emptyUnload": len(empty_unloads),
                                  "decoyMove": len(decoy_moves)},
                       "weights": WEIGHTS, "failedRequests": [{"seq": row.get("seq"), "name": row.get("name"), "status": row.get("status")} for row in failed],
                       "emptyMoves": empty_moves, "decoyMoves": decoy_moves, "emptyUnloads": empty_unloads,
                       "baseIslandBounds": None if bounds is None else [round(v, 1) for v in bounds]}}


def transport_loss(run):
    transports = {row["id"]: row for row in run.meta.get("transports") or []}
    units = {row["id"]: row for row in (run.result.get("units") or [])}
    if not transports or not units:
        return {"id": "transport_loss", "title": "运输机损失", "status": "N/A", "reason": "missing final unit state",
                "cap": TRANSPORT_LOSS["cap"], "raw": 0.0, "detail": {}}
    max_hp = sum(float(units.get(i, {}).get("maxHp") or 0.0) for i in transports)
    remaining = sum(float(units.get(i, {}).get("hp") or 0.0) for i in transports if units.get(i, {}).get("alive"))
    destroyed = sum(1 for i in transports if not units.get(i, {}).get("alive"))
    total = len(transports)
    if max_hp <= 0:
        return {"id": "transport_loss", "title": "运输机损失", "status": "N/A", "reason": "missing max HP", "cap": TRANSPORT_LOSS["cap"], "raw": 0.0}
    hp_ratio = remaining / max_hp
    loss_ratio = 1.0 - hp_ratio
    destroyed_ratio = destroyed / total
    # K1 is the surviving HP share, so (1-K1) is the lost-HP share.
    points = cap(loss_ratio * TRANSPORT_LOSS["hpWeight"] + destroyed_ratio * TRANSPORT_LOSS["destroyedWeight"], TRANSPORT_LOSS["cap"])
    return {"id": "transport_loss", "title": "运输机损失", "status": "OK", "cap": TRANSPORT_LOSS["cap"], "raw": points,
            "detail": {"transports": total, "alive": total - destroyed, "destroyed": destroyed,
                       "remainingHp": round1(remaining), "maxHp": round1(max_hp),
                       "K1RemainingHp": round(hp_ratio, 3), "K1HpLoss": round(loss_ratio, 3),
                       "K2Destroyed": round(destroyed_ratio, 3),
                       "formula": "(1-K1)*5 + K2*15, K1 = remaining/max"}}


def transport_idle(run, end_ms):
    flights = [row for row in run.transport if row.get("kind") == "flight"]
    if not flights:
        return {"id": "transport_idle", "title": "运输机空闲", "status": "N/A", "reason": "missing takeoff/landed evidence",
                "cap": TRANSPORT_IDLE["cap"], "raw": 0.0, "detail": {"segments": []}}
    segments, detail = [], []
    skipped_loaded = skipped_decoy = 0
    transport_ids = sorted({row.get("transportId") for row in run.transport if row.get("transportId") is not None})
    for transport_id in transport_ids:
        own = [row for row in run.transport if row.get("transportId") == transport_id]
        takeoffs = [float(row["gameMs"]) for row in own if row.get("kind") == "flight" and row.get("event") == "takeoff"]
        landings = [float(row["gameMs"]) for row in own if row.get("kind") == "flight" and row.get("event") == "landed"]
        cargo = [float(row["gameMs"]) for row in own if row.get("kind") == "cargo"]
        moves = [float(row["gameMs"]) for row in own if row.get("kind") == "move"]
        damage = [float(row["gameMs"]) for row in own
                  if row.get("kind") == "damage" and row.get("gameMs") is not None]
        first_takeoff = min(takeoffs) if takeoffs else None
        # An empty sortie that takes fire is a decoy/reconnaissance flight; its ground time is not
        # "idle while cargo exists". A loaded transport waiting for takeoff is also not idle by
        # this metric's definition.
        decoy = bool(EXCLUDE_DECOY_SORTIES and first_takeoff is not None
                     and _empty_at(run, transport_id, first_takeoff)
                     and any(hit >= first_takeoff for hit in damage))
        # Ready window: ground time before a takeoff, ended by the previous landing or hold change.
        for takeoff in takeoffs:
            if decoy:
                skipped_decoy += 1
                continue
            if EXCLUDE_LOADED_READY and not _empty_at(run, transport_id, takeoff):
                skipped_loaded += 1
                continue
            marks = [t for t in landings + cargo if t < takeoff]
            start = max(marks) if marks else 0.0
            segments.append(max(0.0, (takeoff - start) / 1000.0))
            detail.append({"transportId": transport_id, "kind": "ready", "startGameMs": round(start, 1),
                           "endGameMs": round(takeoff, 1), "seconds": round((takeoff - start) / 1000.0, 3)})
        # Finished window: ground time after a landing, ended by the next move or hold change.
        for landing in landings:
            if decoy:
                continue
            marks = [t for t in moves + cargo if t > landing]
            end = min(marks) if marks else float(end_ms)
            segments.append(max(0.0, (end - landing) / 1000.0))
            detail.append({"transportId": transport_id, "kind": "finished", "startGameMs": round(landing, 1),
                           "endGameMs": round(end, 1), "seconds": round((end - landing) / 1000.0, 3)})
    points = 0.0
    for segment in detail:
        segment["severity"] = round(piecewise(segment["seconds"], IDLE_SEGMENTS), 3)
        segment["points"] = round1(IDLE_POINTS * segment["severity"])
        points += IDLE_POINTS * segment["severity"]
    return {"id": "transport_idle", "title": "运输机空闲", "status": "OK", "cap": TRANSPORT_IDLE["cap"], "raw": cap(points, TRANSPORT_IDLE["cap"]),
            "detail": {"segments": detail, "perSegmentPoints": IDLE_POINTS,
                       "skippedLoadedReady": skipped_loaded, "skippedDecoySorties": skipped_decoy,
                       "formula": f"{IDLE_POINTS:g}*f(seconds); segments={IDLE_SEGMENTS}"}}


def _baselines():
    return DURATION


def duration_score(run):
    duration = run.result.get("gameMs")
    if duration is None:
        return {"id": "duration", "title": "整体时长", "status": "N/A", "reason": "missing result.gameMs",
                "cap": DURATION["cap"], "raw": 0.0, "detail": {}}
    table = _baselines()
    # Baselines are deliberately per type, not per task/level: the same type shares one T.
    seconds = (table.get("byType") or {}).get(str(run.meta.get("type")))
    source = "per-type baseline"
    if not seconds:
        seconds = 0.55 * float(run.meta.get("limits", {}).get("gameSeconds") or 0)
        source = "0.55 x game limit"
    if not seconds:
        return {"id": "duration", "title": "整体时长", "status": "N/A", "reason": "no baseline duration",
                "cap": DURATION["cap"], "raw": 0.0, "detail": {"durationMs": duration}}
    duration_s = duration / 1000.0
    base = float(seconds)
    low, high = DURATION_LOWER_RATIO * base, DURATION_UPPER_RATIO * base
    if duration_s > high:
        points = DURATION["cap"]
    elif duration_s < low:
        points = DURATION["cap"] * (1.0 - (duration_s / low) ** 2) if low > 0 else DURATION["cap"]
    elif DURATION_QUADRATIC_SPACE == "normalized":
        position = (duration_s - low) / (high - low)
        points = curve(position, 0.0, 1.0, 0.0, DURATION["cap"], "quadratic", QUADRATIC_A)
    elif DURATION_QUADRATIC_SPACE == "minutes":
        points = curve(duration_s / 60.0, low / 60.0, high / 60.0, 0.0, DURATION["cap"], "quadratic", QUADRATIC_A)
    else:
        points = curve(duration_s, low, high, 0.0, DURATION["cap"], "quadratic", QUADRATIC_A)
    return {"id": "duration", "title": "整体时长", "status": "OK", "cap": DURATION["cap"], "raw": cap(points, DURATION["cap"]),
            "detail": {"durationMs": duration, "durationSeconds": round(duration_s, 3), "baselineSeconds": round(base, 3),
                       "baselineSource": source, "ratio": round(duration_s / base, 3) if base else None,
                       "lowerRatio": DURATION_LOWER_RATIO, "upperRatio": DURATION_UPPER_RATIO,
                       "rangeSeconds": [round(low, 1), round(high, 1)], "quadraticA": QUADRATIC_A,
                       "quadraticSpace": DURATION_QUADRATIC_SPACE}}


def compute(run):
    orders, started, moves, unloads = _rows(run)
    end_ms = run.result.get("gameMs") or 0
    entries = [action_delay(run, orders, started), irrelevant(run, moves, unloads),
               transport_loss(run), transport_idle(run, end_ms), duration_score(run)]
    notes = ["每一项独立封顶后求和；缺证据的项记 N/A 且不扣分。",
             "行动延迟：K=sum(weightMax*(min(d,maxSeconds)/maxSeconds)^exponent)/cnt，S=K*scale；"
             "start/end 窗口不贡献权重但仍计入 cnt。",
             "运输机损失用 result.units 的终态 HP；K1=剩余/最大，(1-K1)*5+K2*15。",
             f"整体时长的二次函数横坐标取 {DURATION_QUADRATIC_SPACE}，区间 "
             f"[{DURATION_LOWER_RATIO:g}T,{DURATION_UPPER_RATIO:g}T]；"
             "低于下限按 60*(1-(x/lower)^2) 计。"]
    diagnostics = [{"severity": "info", "reason": item["reason"]} for item in entries if item["status"] != "OK"]
    return document(VERSION, BASELINE, entries, notes, diagnostics)
