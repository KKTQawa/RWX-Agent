"""单局结果解析与适应度打分。"""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

import dataclasses
import json
import math

from .paths import TICKS_PER_SECOND
from .config import TrainConfig

# =========================================================================== 单局结果与打分

@dataclass
class GameRecord:
    map: str
    pair: tuple[int, int]
    candidate_spawn: int
    seed: int
    batch: int
    outcome: str = "error"      # win / loss / draw / error
    ticks: int = 0
    max_ticks: int = 0
    game_ms: float = 0.0
    win: float = 0.0
    prod_self: int = 0
    prod_enemy: int = 0
    def_self: int = 0
    def_enemy: int = 0
    build_prod: float = 0.0
    build_def: float = 0.0
    army_self: float = 0.0
    army_enemy: float = 0.0
    army: float = 0.0
    income_self: float = 0.0
    income_enemy: float = 0.0
    econ: float = 0.0
    econ_ok: bool = False
    end_income_share: float | None = None
    end_building_share: float | None = None
    kill_value: float = 0.0      # 全部单位（含建筑，建筑已乘系数）
    loss_value: float = 0.0
    kill_units: float = 0.0      # 只含军事单位，供战损比使用
    loss_units: float = 0.0
    bld_value: float = 0.0       # 我方摧毁的敌方建筑价值（指挥中心 10000，防御×1.5，其余×1）
    cc_killed: bool = False      # 是否已统计到敌方指挥中心
    exchange_r: float = 0.0
    exchange: float = 0.0      # 仅诊断用，不进奖励
    board: float = 0.0
    army_ratio: float = 0.0     # (敌方损失军队+建筑) / 我方军队损失，未夹紧
    r_unit: float = 0.0         # 只看兵力交换 (y−x)/(y+x)，∈ [-1, 1]
    trade: float = 0.5          # (r_unit+1)/2，输局技能项
    speed: float = 0.0          # 1 − t/T，赢局时间项
    survive: float = 0.0        # t/T，输局时间项
    duration_s: float = 0.0
    time_score: float = 0.0
    reward: float = 0.0
    samples_ok: bool = False
    samples_loss_ok: bool = False
    telemetry_ok: bool = False
    unknown_cost: int = 0
    wall_s: float = 0.0
    error: str = ""

    def to_json(self) -> dict:
        doc = dataclasses.asdict(self)
        doc["pair"] = list(self.pair)
        return doc


_PROD_KEYS = ("factory", "commandcenter")
_DEF_KEYS = ("turret", "defence", "antinuke", "launcher", "repairbay")
_BLD_KEYS = ("extractor", "fabricat", "center", "lab")


def unit_kind(name: str) -> str:
    """把单位类型名归类：prod / def / building / builder / unit。"""
    n = name.lower()
    if any(k in n for k in _PROD_KEYS):
        return "prod"
    if any(k in n for k in _DEF_KEYS):
        return "def"
    if "builder" in n:
        return "builder"
    if any(k in n for k in _BLD_KEYS):
        return "building"
    return "unit"


def gap(mine: float, theirs: float) -> float:
    """差异比例 (我 - 敌) / (我 + 敌)，[-1, 1]，双方都为 0 时取 0。"""
    total = mine + theirs
    return (mine - theirs) / total if total > 0 else 0.0


def building_destruction_value(name: str, cost: float, cfg: "TrainConfig") -> float:
    """我方摧毁敌方建筑时的计分价值：指挥中心固定 10000，防御×1.5（K1），其余×1（K2）。"""
    n = name.lower()
    if "commandcenter" in n or "command_center" in n:
        return 10000.0
    if unit_kind(name) == "def":
        return cost * 1.5
    return cost * 1.0


def enemy_spawn_of(rec: GameRecord) -> int:
    a, b = rec.pair
    return b if rec.candidate_spawn == a else a


def parse_telemetry(game_dir: Path, rec: GameRecord, cfg: "TrainConfig", costs: dict) -> None:
    """从 telemetry 取死亡事件（K/L）并采集单位造价。

    telemetry 的 side 相对它跟踪的队伍（meta.team），候选在另一侧时敌我要反过来。
    """
    files = sorted(game_dir.glob("events-live/*/telemetry.jsonl"))
    if not files:
        return
    rec.telemetry_ok = True
    end_ms = rec.game_ms or rec.ticks / TICKS_PER_SECOND * 1000.0
    death_end_ms = max(0.0, end_ms - cfg.death_end_margin_ms)
    my_team = rec.candidate_spawn - 1

    for path in files:
        self_is_mine = True
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if '"meta"' in line and '"team"' in line:
                    row = read_json_line(line)
                    if row.get("kind") == "meta" and row.get("team") is not None:
                        self_is_mine = int(row["team"]) == my_team
                    continue
                if '"death"' not in line and '"unit"' not in line:
                    continue
                row = read_json_line(line)
                kind = row.get("kind")
                if kind == "unit":
                    for act in (row.get("unit") or {}).get("actions", {}).values():
                        if act.get("kind") == "produce" and act.get("type"):
                            costs.setdefault(str(act["type"]).lower(), float(act.get("cost") or 0.0))
                    continue
                if kind != "death":
                    continue
                unit, killer = row.get("unit") or {}, row.get("killer") or {}
                # 排除：无击杀者（自毁/撤销建造）、同阵营击杀、局终清场
                if not unit.get("type") or not killer or killer.get("side") == unit.get("side"):
                    continue
                if float(row.get("timeMs") or 0.0) > death_end_ms:
                    continue
                cost = costs.get(str(unit["type"]).lower())
                if cost is None:
                    cost, rec.unknown_cost = cfg.default_unit_cost, rec.unknown_cost + 1
                if unit.get("building"):
                    cost *= cfg.building_value_weight
                elif unit.get("builder"):
                    cost *= cfg.builder_value_weight
                mine = (unit.get("side") == "self") == self_is_mine
                kind = unit_kind(str(unit.get("type") or ""))
                military = kind == "unit"
                if mine:
                    rec.loss_value += cost
                    rec.loss_units += cost if military else 0.0
                else:
                    rec.kill_value += cost
                    if military:
                        rec.kill_units += cost
                    else:
                        rec.bld_value += building_destruction_value(str(unit.get("type") or ""), cost, cfg)


def read_json_line(line: str) -> dict:
    try:
        return json.loads(line)
    except Exception:
        return {}


def parse_final_board(result: dict, rec: GameRecord, slots: list[dict]) -> None:
    """Aggregate end-of-match credit income and live building cost by the requested sides."""
    teams = {team["teamId"]: team for team in result.get("teams", ())}
    income = [0.0, 0.0]
    buildings = [0.0, 0.0]
    for slot in slots:
        team = teams.get(slot["spawn"] - 1, {})
        rate, cost = team.get("incomePerSecond"), team.get("buildingCost")
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (rate, cost)):
            raise ValueError("Hard-up v3 draw scoring needs terminal incomePerSecond and buildingCost; "
                             "rebuild and use the current headless distribution")
        side = slot["side"]
        income[side] += max(0.0, rate)
        buildings[side] += cost
    rec.end_income_share = income[0] / sum(income) if sum(income) > 0 else 0.5
    rec.end_building_share = buildings[0] / sum(buildings) if sum(buildings) > 0 else 0.5


def clip01(value: float) -> float:
    return min(1.0, max(0.0, value))


def parse_samples(game_dir: Path, rec: GameRecord, cfg: "TrainConfig", costs: dict) -> None:
    """取“终局前一段”（默认 75% 时长）的快照：建筑、兵力、收入，以及累计战损。

    不用最后一帧：输掉的局末帧必然被打光，差距恒 ≈ -1，方差只反映“输得多惨”。
    """
    path = game_dir / "samples.jsonl"
    if not path.exists():
        return
    rows: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = read_json_line(line)
                if row:
                    rows.append(row)
    if not rows:
        return

    final_tick = rows[-1].get("tick") or 0
    target = float(final_tick) * cfg.snapshot_fraction
    snapshot = min(rows, key=lambda r: abs(float(r.get("tick") or 0) - target))
    mine_id, their_id = str(rec.candidate_spawn - 1), str(enemy_spawn_of(rec) - 1)

    def side(row: dict, team_id: str):
        team = (row.get("teams") or {}).get(team_id) or {}
        prod = dfn = 0
        army = 0.0
        for name, count in (team.get("types") or {}).items():
            kind = unit_kind(name)
            if kind == "prod":
                prod += count
            elif kind == "def":
                dfn += count
            elif kind == "unit":
                army += count * (costs.get(name.lower()) or cfg.default_unit_cost)
        income = team.get("incomePerSecond")
        return prod, dfn, army, (float(income) if isinstance(income, (int, float)) else None)

    rec.prod_self, rec.def_self, rec.army_self, mine = side(snapshot, mine_id)
    rec.prod_enemy, rec.def_enemy, rec.army_enemy, theirs = side(snapshot, their_id)
    rec.samples_ok = True
    if mine is not None and theirs is not None:
        rec.income_self, rec.income_enemy, rec.econ_ok = mine, theirs, True

    # 累计战损：相邻采样之间某类型数量下降就是损失
    if not rec.telemetry_ok:
        prev = None
        for row in rows:
            cur = row.get("teams") or {}
            if prev is not None:
                for team_id, is_mine in ((mine_id, True), (their_id, False)):
                    before = ((prev.get(team_id) or {}).get("types") or {})
                    after = ((cur.get(team_id) or {}).get("types") or {})
                    for name, count in before.items():
                        drop = count - int(after.get(name, 0))
                        if drop <= 0:
                            continue
                        cost = costs.get(name.lower()) or cfg.default_unit_cost
                        military = unit_kind(name) == "unit"
                        if is_mine:
                            rec.loss_value += drop * cost
                            rec.loss_units += drop * cost if military else 0.0
                        else:
                            rec.kill_value += drop * cost
                            if military:
                                rec.kill_units += drop * cost
                            else:
                                rec.bld_value += drop * building_destruction_value(name, cost, cfg)
                                if "commandcenter" in name.lower():
                                    rec.cc_killed = True
            prev = cur
        rec.samples_loss_ok = rec.kill_value + rec.loss_value > 0


def score(rec: GameRecord, cfg: "TrainConfig") -> None:
    """单局奖励：胜负 + 建筑差距 + 兵力差距 + 战损比 + 用时 + 收入差。"""
    win = {"win": 1.0, "draw": 0.5, "loss": 0.0}.get(rec.outcome)
    if win is None:
        rec.reward = float("-inf")
        return
    rec.win = win

    if rec.samples_ok:
        rec.build_prod = gap(rec.prod_self, rec.prod_enemy)
        rec.build_def = gap(rec.def_self, rec.def_enemy)
    if rec.econ_ok:
        rec.econ = gap(rec.income_self, rec.income_enemy)
    # 胜利条件就是“敌方指挥中心全灭”；采样可能在同 tick 结束、捕捉不到最后一次消失，
    # 这时按规则补记一个指挥中心的价值，保证赢局的 z 至少包含它。
    if rec.outcome == "win" and not rec.cc_killed:
        rec.bld_value += 10000.0
        rec.kill_value += 10000.0

    if rec.telemetry_ok or rec.samples_loss_ok:
        # army（净交换率，含建筑）＝(战果 − 损失) / (战果 + 损失)，∈ [-1, 1]
        x, y, z = rec.loss_units, rec.kill_units, rec.bld_value
        gain, loss = y + z, x
        rec.army = (gain - loss) / (gain + loss + 1e-6)
        rec.army_ratio = (gain + 1e-6) / (loss + 1e-6)
        # r_unit / trade：只看兵力交换，供输局奖励使用（不含建筑，避免“输着拆家刷分”）
        rec.r_unit = (y - x) / (y + x + 1e-6)
        rec.trade = 0.5 * (rec.r_unit + 1.0)
        k, l = y, x
        rec.exchange = k / (k + l) if k + l > 0 else 0.5
        rec.exchange_r = min(999.0, k / max(1e-6, l))

    v3 = cfg.scenario == "hardupv3"
    limit_s = 3600.0 if v3 else max(1.0, cfg.win_time_limit)
    survival_limit_s = 5400.0 if v3 else limit_s
    rec.duration_s = rec.game_ms / 1000.0 if rec.game_ms > 0 else rec.ticks / TICKS_PER_SECOND
    rec.speed = clip01(1.0 - rec.duration_s / limit_s)
    rec.survive = clip01(rec.duration_s / survival_limit_s)
    rec.time_score = rec.speed if rec.outcome == "win" else (rec.survive if rec.outcome == "loss" else 0.0)

    # 奖励 v2：胜负分档，两档各 0.30 的“技能 + 时间”额度
    #   赢局看「多快赢 + 推进多少」，输局看「撑多久 + 兵力交换多好」；
    #   输局用 r_unit（只看兵力），避免输的时候靠拆建筑刷交换比。
    rec.board = 0.0
    if rec.outcome == "win":
        rec.reward = (cfg.w_win + cfg.w_win_offense * min(1.0, max(0.0, rec.army))
                      + cfg.w_win_time * rec.speed)
    elif rec.outcome == "draw":
        if v3:
            if rec.end_income_share is None or rec.end_building_share is None:
                raise ValueError("Hard-up v3 draw scoring requires terminal board shares")
            economy = clip01(0.5 + 2 * (rec.end_income_share - 0.5))
            buildings = clip01(1.5 - 2 * rec.end_building_share)
            rec.reward = 0.20 + 0.06 * economy + 0.09 * buildings
        else:
            rec.reward = cfg.legacy_draw_base + cfg.w_win_time * rec.speed
    else:
        rec.reward = (cfg.w_loss_trade * rec.trade + cfg.w_loss_time * rec.survive)
