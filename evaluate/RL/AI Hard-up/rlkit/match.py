"""对局规格：地图池、抽样、批量切分。"""
from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

import random

from .util import read_json

# =========================================================================== 对局规格

@dataclass(frozen=True)
class Matchup:
    name: str
    map: str
    pair: tuple[int, int]
    # 固定布局（2v2 等）：((spawn, role), ...)，role ∈ {"candidate","opponent"}；None = 传统 1v1。
    teams: tuple[tuple[int, str], ...] | None = None

    @property
    def is_team_game(self) -> bool:
        return bool(self.teams)


@dataclass(frozen=True)
class MatchSpec:
    """一局：图 + 双方出生点 + 槽位 + 种子 + 批次。

    槽位要轮换：AI 难度收入倍率只作用于 AI 队，候选固定坐槽 0 会一直吃亏。
    """

    matchup: Matchup
    candidate_spawn: int
    seed: int
    batch: int
    candidate_slot: int = 0

    @property
    def opponent_spawn(self) -> int:
        a, b = self.matchup.pair
        return b if self.candidate_spawn == a else a


def load_pool(path: Path) -> list[Matchup]:
    doc = read_json(Path(path)) or {}
    entries: list[Matchup] = []
    for item in doc.get("maps") or []:
        name = str(item.get("name") or Path(str(item["map"])).stem)
        teams = item.get("teams")
        if teams:
            # 固定布局：出生点与角色都写死（2v2 = 1/3 我方、2/4 对手），不做奇偶轮换。
            layout = tuple((int(t["spawn"]), str(t["ai"]).strip().lower()) for t in teams)
            if len(layout) < 2 or layout[0][1] != "candidate":
                raise SystemExit(f"{name}: teams 必须以 candidate 开头，且有至少两队")
            spawns = [spawn for spawn, _ in layout]
            if len(set(spawns)) != len(spawns):
                raise SystemExit(f"{name}: teams 的出生点不能重复")
            entries.append(Matchup(name, str(item["map"]), (spawns[0], spawns[1]), layout))
            continue
        for pair in item.get("pairs") or [[1, 2]]:
            pair = tuple(int(x) for x in pair)
            if len(pair) != 2 or pair[0] == pair[1]:
                raise SystemExit(f"{name}: pairs 必须是两个不同的出生点编号")
            entries.append(Matchup(name, str(item["map"]), pair))
    if not entries:
        raise SystemExit(f"配置池是空的：{path}")
    return entries


def sample(entries: list[Matchup], count: int, rng: random.Random) -> list[Matchup]:
    """无放回抽样；池子不够大就整池打乱后重复。"""
    out: list[Matchup] = []
    while len(out) < count:
        out.extend(rng.sample(entries, len(entries)))
    return out[:count]


def make_specs(entries, rng, n_games: int, batch_size: int, phase: int = 0) -> list[MatchSpec]:
    """抽 n_games 局。

    先按“地图”等概率抽取（同一张图的多个 pair 只算一次机会），选中地图后再在它的
    配置里均匀挑一个；否则配置多的大图会被不成比例地抽到。
    出口固定：出生点与槽位都奇偶交替（各一半），按 batch_size 分批。
    """
    by_map: dict[str, list[Matchup]] = {}
    for entry in entries:
        by_map.setdefault(entry.name, []).append(entry)
    names = list(by_map)
    picks = [rng.choice(by_map[rng.choice(names)]) for _ in range(n_games)]
    # phase 让“候选坐哪个槽位/出生点”跨代轮换：每代只有少数几局时也能对半分
    return [MatchSpec(m, m.pair[0] if m.is_team_game else m.pair[(i + phase) % 2],
                      rng.randrange(1, 2_000_000_000),
                      i // max(1, batch_size),
                      candidate_slot=0 if m.is_team_game else (i + phase) % 2)
            for i, m in enumerate(picks)]
