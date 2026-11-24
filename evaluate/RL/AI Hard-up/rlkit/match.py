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
    # 固定布局：((spawn, role), ...)，role 为 candidate、opponent 或内置对手 ID。
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
            # 引擎按 spawn 装 AI、按槽位落阵营，所以列表顺序必须就是 spawn 1..N（槽位 = spawn-1），
            # 且我方不一定要坐 1 号出生点（3v3 以上的奇偶对调会把我方放到 2/4/6）。
            layout = tuple((int(t["spawn"]), str(t["ai"]).strip().lower()) for t in teams)
            if len(layout) < 2:
                raise SystemExit(f"{name}: teams 至少两队")
            roles = [role for _, role in layout]
            if "candidate" not in roles or all(role == "candidate" for role in roles):
                raise SystemExit(f"{name}: teams 必须同时指定候选方和对手")
            if any(role not in ("candidate", "opponent") and not role.startswith("rwx.original.")
                   for role in roles):
                raise SystemExit(f"{name}: teams[].ai 须为 candidate、opponent 或内置 AI ID")
            spawns = [spawn for spawn, _ in layout]
            if len(set(spawns)) != len(spawns):
                raise SystemExit(f"{name}: teams 的出生点不能重复")
            if spawns != list(range(1, len(spawns) + 1)):
                raise SystemExit(f"{name}: teams 必须按 spawn 1..N 连续排列（槽位 = spawn-1）")
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


def candidate_seat(matchup: Matchup, phase: int, index: int) -> tuple[int, int]:
    """候选坐哪：(出生点, 槽位)。

    组队局必须按 ``teams`` 里第一个 ``candidate`` 的真实位置算，不能固定 0：
    pB 阵型里 slot 0 是对手（引擎按第一个队伍写胜负、样本也按槽位取数），
    固定 0 会把整局的胜负与我方/敌方指标一起对调。
    """
    if matchup.is_team_game:
        slot = next(k for k, (_, role) in enumerate(matchup.teams) if role == "candidate")
        return matchup.teams[slot][0], slot
    slot = (index + phase) % 2
    return matchup.pair[slot], slot


def make_specs(entries, rng, n_games: int, batch_size: int, phase: int = 0) -> list[MatchSpec]:
    """抽 n_games 局。

    先按“地图”等概率抽取（同一张图的多个 pair 只算一次机会），选中地图后再在它的
    配置里均匀挑一个；否则配置多的大图会被不成比例地抽到。
    出口固定：1v1 的出生点与槽位奇偶交替（各一半），组队局按阵型自己的座位，按 batch_size 分批。
    """
    by_map: dict[str, list[Matchup]] = {}
    for entry in entries:
        by_map.setdefault(entry.name, []).append(entry)
    names = list(by_map)
    picks = [rng.choice(by_map[rng.choice(names)]) for _ in range(n_games)]
    # phase 让“候选坐哪个槽位/出生点”跨代轮换：每代只有少数几局时也能对半分
    specs = []
    for i, m in enumerate(picks):
        spawn, slot = candidate_seat(m, phase, i)
        specs.append(MatchSpec(m, spawn, rng.randrange(1, 2_000_000_000),
                               i // max(1, batch_size), candidate_slot=slot))
    return specs


if __name__ == "__main__":
    # 自检：pA 候选在 slot 0 / 出生点 1，pB 在 slot 1 / 出生点 2；1v1 仍按 phase 交替。
    import random as _random

    teams_a = tuple((s, "candidate" if s % 2 else "opponent") for s in range(1, 7))
    teams_b = tuple((s, "opponent" if s % 2 else "candidate") for s in range(1, 7))
    pool = [Matchup("a", "m.tmx", (1, 2), teams_a), Matchup("b", "m.tmx", (1, 2), teams_b),
            Matchup("solo", "m.tmx", (1, 2))]
    specs = make_specs(pool, _random.Random(0), 30, 1)
    for s in specs:
        if s.matchup.name == "a":
            assert (s.candidate_spawn, s.candidate_slot) == (1, 0), s
        elif s.matchup.name == "b":
            assert (s.candidate_spawn, s.candidate_slot) == (2, 1), s
        else:
            assert s.candidate_spawn in (1, 2) and s.candidate_slot == s.candidate_spawn - 1, s
    assert {s.candidate_slot for s in specs if s.matchup.name == "solo"} == {0, 1}
    print("match.py 自检通过")
