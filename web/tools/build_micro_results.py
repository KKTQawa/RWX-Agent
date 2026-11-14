#!/usr/bin/env python3
"""Build `web/resource/micro-results.json` from the collected CASE runs.

Every number on the CASE section of the site comes from the runs themselves, so the page cannot
drift away from what the scorer produced:

* per-record points/raw come from `eval/metrics.json` (`score.items`);
* the rule table (cap + formula) is rendered from each CASE's `config.json`, so a changed cap or
  curve shows up as soon as the file is rebuilt;
* the four DSH runs of CASE1/CASE3/CASE4 were evaluated in an external workspace that is no longer
  on disk, so their per-item numbers are transcribed from
  `evaluate/output/micro/_review-20261112-dsh-four-cases.md` (EXTERNAL below) and cross-checked
  against the recorded total. CASE2's DSH run was re-collected locally, so it is read like any other
  run and the CASE carries two agent records instead of an external one.
"""
from __future__ import annotations
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent
MICRO = ROOT / 'evaluate' / 'output' / 'micro'
MICRO_CONFIG = ROOT / 'evaluate' / 'micro'
OUT = WEB / 'resource' / 'micro-results.json'

CASES = [
    ('CASE1-duel', 'CASE 01', '遭遇战与撤离',
     '3v3 近战遭遇：在受损与火力压力中撤离，观察初始响应、集体空窗与单位损失。',
     './resource/cases/case1.webp', './resource/CASE1-human.mp4',
     'CASE1 真实游戏窗口截图：程序生成草地上分布着水域与悬崖',
     '80–120 格程序生成草地或 111×111 固定环湖图。玩家控制 3 台机枪机甲，对抗 2–5 台猛犸坦克；'
     '水域与悬崖造成机动差异，目标是在 600 s 内歼灭敌军。'),
    ('CASE2-LTE', 'CASE 02', '持续生产与增援',
     '持续经营任务：生产、编队与行动是否被观察和工具调用阻塞。',
     './resource/cases/case2.webp', './resource/CASE2-脚本基线.mp4',
     'CASE2 真实游戏窗口截图：单个建造者位于分散资源池之间',
     '55–73 格正方形草地，4–8 个资源池按泊松盘分散，唯一建造者出生在中心，初始资金 2100。'
     '没有敌人；任务是在限定时间内建造并升级提取器，把收入做到目标档次。'),
    ('CASE3-Transport', 'CASE 03', '运输与登陆',
     '跨区域运输：把生产、载具调度、航线与落点选择放进同一个实时链路。',
     './resource/cases/case3.webp', './resource/CASE3-脚本基线.mp4',
     'CASE3 真实游戏窗口截图：岩浆中的目标岛上布置四座防空塔',
     '130×130 岩浆地图，左上目标岛与右下基地岛完全分离。基地提供工厂、经济建筑和运输机；'
     'Agent 要生产指定陆军，规划装载、飞行与卸载，把完整编成送到目标岛。'),
    ('CASE4-Retreat', 'CASE 04', '受压防守与维修',
     '在固定火力压力下完成撤退、修理与持续防守，区分短时失误与完全失败。',
     './resource/cases/case4.webp', './resource/CASE4-human.mp4',
     'CASE4 真实游戏窗口截图：草地战场上的炮塔区初始画面',
     '65–69 格全草地矩形图。左上 3/5 区域布置近程/远程炮塔，右下角以 L 形排列维修湾和 1–3 台虫王'
     '（bugMeleeT31，近战无护盾）；任务是清空炮塔并在受损时撤回维修。'),
]

# Materials live outside the repository (see the review report); keep the recorded per-item numbers.
# `raw` is the scorer's own raw value, `points` the value after the per-item cap. A CASE whose runs
# were all collected locally has no entry here.
EXTERNAL = {
    'CASE1-duel': {
        'run': 'CASE1-duel_1_2_2_realtime_s1331_20261112-224151', 'score': 30.8,
        'outcome': 'loss', 'seconds': 67.040, 'model': 'deepseek-v4.1-flash', 'tool': 'DSH',
        'items': {'irrelevant': (0.0, 30, 0.0), 'mech_damage': (59.5, 60, 59.5),
                  'collective_idle': (9.719, 40, 9.7)}},
    'CASE3-Transport': {
        'run': 'CASE3-Transport_3_3_1_realtime_s1331_20261112-224233', 'score': 15.1,
        'outcome': 'success', 'seconds': 336.144, 'model': 'deepseek-v4.1-flash', 'tool': 'DSH',
        'items': {'action_delay': (46.289, 40, 40.0), 'irrelevant': (4.5, 20, 4.5),
                  'transport_loss': (8.467, 15, 8.5), 'transport_idle': (0.0, 0, 0.0),
                  'duration': (31.959, 60, 32.0)}},
    'CASE4-Retreat': {
        'run': 'CASE4-Retreat_4_2_1_realtime_s1331_20261112-224251', 'score': 20.2,
        'outcome': 'defeat', 'seconds': 25.200, 'model': 'deepseek-v4.1-flash', 'tool': 'DSH',
        'items': {'tank_loss': (50.0, 50, 50.0), 'tank_idle': (0.0, 30, 0.0),
                  'duration': (29.827, 30, 29.8)}},
}
EXTERNAL_SOURCE = 'evaluate/output/micro/_review-20261112-dsh-four-cases.md'

OUTCOME = {'win': '胜利', 'loss': '失败', 'success': '成功', 'defeat': '失败', 'timeout': '超时'}
MODEL_SLUG = {'DeepSeek V4.1 Flash': 'deepseek-v4.1-flash'}

# Item prose keyed by scorer id. Caps and formulas are read from config, never written here.
DOC = {
    'irrelevant': ('卡死 / 无关行为',
                   '惩罚越权请求、失败或重复指令，以及没有可作用目标的动作。'),
    'mech_damage': ('机枪机甲承受伤害', '阵亡单独重罚，存活机甲的生命与护盾损耗按比例计入。'),
    'collective_idle': ('集体空闲', '所有存活机甲同时 idle，且没有及时开火的窗口。'),
    'action_delay': ('行动延迟', '资金已够且执行单位空闲后，建造或升级仍被延后的时间。'),
    'cadence': ('底层命令执行间隔', '同时衡量总体操作节奏与偶发的超长停顿。'),
    'transport_loss': ('运输机损失', '兼顾受损程度与整机损失。'),
    'transport_idle': ('运输机空闲', '统计起飞前已就绪却未行动，以及落地完成后没有继续调度的窗口。'),
    'duration': ('整体时长', '以同 type 基线 T 为参照：越快完成，扣分越少。'),
    'tank_loss': ('虫王损失', '直接惩罚主力近战单位阵亡。'),
    'tank_idle': ('虫王空闲', '维修完成后仍停留，或在战场外无意义滞留都会计入。'),
}
ORDER = ['irrelevant', 'mech_damage', 'collective_idle', 'action_delay', 'cadence',
         'transport_loss', 'transport_idle', 'tank_loss', 'tank_idle', 'duration']


def read(path: Path, default=None):
    return json.loads(path.read_text(encoding='utf-8').replace('\ufeff', '')) if path.is_file() else default


def slug(model_id: str) -> str:
    if model_id in MODEL_SLUG:
        return MODEL_SLUG[model_id]
    return re.sub(r'[^a-z0-9.]+', '-', model_id.lower()).strip('-')


def num(value):
    return f'{value:g}'


def rules(case_id: str, config: dict):
    """Current rule per item, rendered from the CASE config so it cannot go stale."""
    evaluation = config.get('evaluation') or {}
    items = {}

    def add(key, cap, formula):
        name, description = DOC[key]
        items[key] = {'id': key, 'name': name, 'cap': cap, 'formula': formula, 'description': description}

    if 'irrelevant' in evaluation:
        weights = evaluation['irrelevant']['weights']
        parts = []
        for key, label in (('violation', '违规'), ('failed', '失败行动'), ('wasted', '浪费/失败指令'),
                           ('noop', '无效果动作'), ('waste', '无效运输动作'), ('surplus', '超出目标')):
            if key in weights:
                parts.append(f'{num(weights[key])}×{label}')
        add('irrelevant', evaluation['irrelevant']['cap'], ' + '.join(parts) + '，合计封顶')

    if 'mechDamage' in evaluation:
        damage = evaluation['mechDamage']
        add('mech_damage', damage['cap'],
            f"K×{num(damage['killWeight'])} + A₁/B₁×{num(damage['hpWeight'])} + "
            f"A₂/B₂×{num(damage['shieldWeight'])}；K=阵亡占比，A/B=受损与原始池")

    if 'collectiveIdle' in evaluation:
        idle = evaluation['collectiveIdle']
        low, high = idle['clampSeconds']
        add('collective_idle', idle['cap'],
            f"Σ {num(idle['points'])}×((clamp(L,{num(low)},{num(high)})−{num(low)})/"
            f"{num(high - low)})^{num(idle['exponent'])}；L≥{num(idle['minSeconds'])}s 的窗口逐段累加")

    if 'actionDelay' in evaluation:
        delay = evaluation['actionDelay']
        floor = delay.get('countFloor')
        denominator = f"max(cnt,{num(floor)})" if floor else "cnt"
        add('action_delay', delay['cap'],
            f"w={num(delay['weightMax'])}×(min(d,{num(delay['maxSeconds'])})/"
            f"{num(delay['maxSeconds'])})^{num(delay['exponent'])}；K=Σw/{denominator}；"
            f"S=K×{num(delay['scale'])}")

    if 'cadence' in evaluation:
        cadence = evaluation['cadence']
        mean_low, mean_high = cadence['meanSeconds']
        out_low, out_high = cadence['outlierSeconds']
        scale = cadence.get('overallScale')
        scaled = f"，加权后 ×{num(scale)}" if scale else ""
        add('cadence', cadence['cap'],
            f"S=({num(cadence['meanWeight'])}×f(去离群均值) + {num(cadence['outlierWeight'])}×ΣP(离群)){scaled}；"
            f"f 在 {num(mean_low)}–{num(mean_high)}s 取幂 {num(cadence['meanExponent'])}，"
            f"P 在 {num(out_low)}–{num(out_high)}s 取幂 {num(cadence['outlierExponent'])}，"
            f"异常项封顶 {num(cadence['anomalyCap'])}")

    if 'transportLoss' in evaluation:
        loss = evaluation['transportLoss']
        add('transport_loss', loss['cap'],
            f"S=(1−K₁)×{num(loss['hpWeight'])} + K₂×{num(loss['destroyedWeight'])}；"
            f"K₁=剩余 HP 占比，K₂=阵亡占比")

    if 'transportIdle' in evaluation:
        idle = evaluation['transportIdle']
        segments = '，'.join(f'{num(seg[0])}–{num(seg[1])}s→{num(seg[3])}' for seg in idle['segments'])
        add('transport_idle', idle['cap'],
            f"Σ {num(idle['points'])}×f(L)；分段 {segments}"
            + ('；当前 cap=0，本项暂停计分' if idle['cap'] == 0 else ''))

    if 'duration' in evaluation:
        duration = evaluation['duration']
        lower = float(duration['lowerRatio'])
        upper = float(duration['upperRatio'])
        if duration.get('curve') == 'poly-ratio':
            # Polynomial in x = duration / T, normalised so y(2T) ~ 1: CASE2's current curve.
            raw = [float(value) for value in duration['coefficients']]
            a, b, c = num(raw[0]), num(raw[1]), num(raw[2])
            sign = '' if raw[2] < 0 else '+'
            add('duration', duration['cap'],
                f"x=d/T；d<{num(lower)}T：0；{num(lower)}T–{num(upper)}T："
                f"y={a}x²+{b}x{sign}{c}，扣分={num(duration['cap'])}y；>{num(upper)}T 取满")
        elif 'k' in duration:
            # Exponential in the normalised position.
            k = num(duration['k'])
            power = "u²" if k == "1" else f"{k}u²"
            add('duration', duration['cap'],
                f"d<{num(lower)}T：0；{num(lower)}T–{num(upper)}T：u=(d−{num(lower)}T)/{num(upper - lower)}T，"
                f"{num(duration['cap'])}×(exp({power})−1)/(exp({k})−1)；>{num(upper)}T 取满")
        else:
            add('duration', duration['cap'],
                f"d<{num(lower)}T：{num(duration['cap'])}×(1−(d/{num(lower)}T)²)；"
                f"{num(lower)}T–{num(upper)}T：过 ({num(lower)}T,0) 与 ({num(upper)}T,{num(duration['cap'])}) "
                f"的 a={num(duration['quadraticA'])} 二次曲线；>{num(upper)}T 取满")

    if 'tankLoss' in evaluation:
        loss = evaluation['tankLoss']
        add('tank_loss', loss['cap'], f"S={num(loss['scale'])}×K₁；K₁=阵亡虫王/任务虫王")

    if 'tankIdle' in evaluation:
        idle = evaluation['tankIdle']
        weights = idle['weights']
        minimum = idle['minSeconds']
        add('tank_idle', idle['cap'],
            f"w={num(weights['ready'])}Σ(A−{num(minimum['ready'])}) + "
            f"{num(weights['loiter'])}Σ(B−{num(minimum['loiter'])})；S={num(idle['scale'])}×(w/T)/R，"
            f"R 取基线或 {num(idle['ratioDefault'] * 100)}%")

    return [items[key] for key in ORDER if key in items]


def load_runs(case: str):
    runs = []
    for directory in sorted((MICRO / case).iterdir()):
        if not directory.is_dir():
            continue
        meta = read(directory / 'meta.json')
        metrics = read(directory / 'eval' / 'metrics.json')
        result = read(directory / 'result.json', {}) or {}
        if not meta or not metrics:
            continue
        runs.append({'dir': directory, 'name': directory.name, 'meta': meta, 'metrics': metrics,
                     'score': (metrics.get('score') or {}).get('total'),
                     'version': (metrics.get('score') or {}).get('version'),
                     'outcome': result.get('outcome') or (metrics.get('evidence') or {}).get('playback', {}).get('outcome'),
                     'seconds': round(result['gameMs'] / 1000, 3) if result.get('gameMs') is not None else None,
                     'models': meta.get('models') or [], 'tools': meta.get('tools') or []})
    return runs


def agent_identity(run):
    model = run['models'][0] if run['models'] else {}
    tool = run['tools'][0] if run['tools'] else {}
    return {'model': slug(model.get('id', 'unknown')), 'tool': tool.get('profile') or tool.get('name') or 'unknown',
            'provider': model.get('provider'), 'thinking': model.get('thinking')}


def scored_items(run):
    """id -> {raw, cap, points} straight from the scorer output."""
    return {item['id']: {'raw': item.get('raw'), 'cap': item.get('cap'), 'points': item.get('points')}
            for item in (run['metrics'].get('score') or {}).get('items', [])}


def build_case(case_id, label, title, description, image, video, image_alt, environment):
    config = read(MICRO_CONFIG / case_id / 'config.json', {}) or {}
    runs = load_runs(case_id)
    agents = sorted((run for run in runs if run['models']), key=lambda run: run['name'])
    if not agents:
        raise SystemExit(f'{case_id}: expected at least one agent run with model metadata')
    agent = agents[0]
    task = agent['meta'].get('task')
    baselines = [run for run in runs if not run['models'] and run['meta'].get('mode') == 'agent'
                 and run['meta'].get('task') == task]
    humans = [run for run in runs if run['meta'].get('mode') == 'human' and run['meta'].get('task') == task]
    if not baselines:
        raise SystemExit(f'{case_id}: no baseline run for task {task}')
    baseline = baselines[-1]
    records = [{
        'kind': 'baseline', 'kindLabel': '脚本基线', 'detail': 'baseline · greedy 策略',
        'score': baseline['score'], 'note': OUTCOME.get(baseline['outcome'], baseline['outcome'] or '未知'),
        'seconds': baseline['seconds'], 'run': baseline['name'], 'task': task,
        'scoreVersion': baseline['version'], 'source': 'evaluate/output/micro/' + case_id,
        'items': scored_items(baseline),
    }]
    external = EXTERNAL.get(case_id)
    if external:
        records.append({
            'kind': 'agent', 'kindLabel': external['model'], 'detail': f"{external['tool']} · 外部材料",
            'score': external['score'], 'note': OUTCOME.get(external['outcome'], external['outcome']),
            'seconds': external['seconds'], 'run': external['run'], 'task': task,
            'scoreVersion': f'case{case_id[4]}-score-v1', 'source': EXTERNAL_SOURCE,
            'items': {key: {'raw': raw, 'cap': cap, 'points': points}
                      for key, (raw, cap, points) in external['items'].items()},
        })
    for agent in agents:
        identity = agent_identity(agent)
        # A repeat run carries `meta.attempt`; keep it in the tool label so the matrix and the tool
        # average still separate "Pi 01" from "Pi 02" while `detail.split(" ")[0]` stays the harness.
        tool = identity['tool']
        attempt = agent['meta'].get('attempt')
        if attempt:
            tool = f"{tool} {int(attempt):02d}"
        records.append({
            'kind': 'agent', 'kindLabel': identity['model'],
            'detail': ' · '.join(value for value in (tool, identity['provider']) if value),
            'score': agent['score'], 'note': OUTCOME.get(agent['outcome'], agent['outcome'] or '未知'),
            'seconds': agent['seconds'], 'run': agent['name'], 'task': task,
            'scoreVersion': agent['version'], 'source': 'evaluate/output/micro/' + case_id,
            'items': scored_items(agent),
        })
    for human in humans:
        records.append({
            'kind': 'human', 'kindLabel': '人类', 'detail': 'manual',
            'score': human['score'], 'note': OUTCOME.get(human['outcome'], human['outcome'] or '未知'),
            'seconds': human['seconds'], 'run': human['name'], 'task': task,
            'scoreVersion': human['version'], 'source': 'evaluate/output/micro/' + case_id,
            'items': scored_items(human),
        })

    items = rules(case_id, config)
    # A rebuilt rule table that disagrees with the runs would put two versions of the same cap on
    # one page; fail loudly instead of publishing it.
    for record in records:
        for item in items:
            recorded = record['items'].get(item['id'], {}).get('cap')
            if recorded is not None and abs(recorded - item['cap']) > 1e-9:
                raise SystemExit(f"{case_id}/{record['kind']}: {item['id']} cap {recorded} != config {item['cap']}")
        total = sum(value['points'] or 0 for value in record['items'].values())
        if abs((100 - total) - record['score']) > 0.15:
            raise SystemExit(f"{case_id}/{record['kind']}: items sum to {100 - total:.2f}, "
                             f"recorded score {record['score']}")

    return {'label': label, 'title': title, 'description': description, 'image': image, 'video': video,
            'imageAlt': image_alt, 'imageCaption': f'真实游戏窗口截图 · {title}开局画面',
            'environment': environment, 'case': case_id, 'task': task,
            'seed': agent['meta'].get('seed'), 'scoreVersion': agent['version'],
            'items': items, 'records': records}


data = {'generatedAt': None, 'cases': [build_case(*case) for case in CASES]}
OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'Wrote {OUT}')
for case in data['cases']:
    print(' ', case['case'], case['task'], len(case['items']), 'items |',
          ' | '.join(f"{r['kind']}/{r['detail']}={r['score']}" for r in case['records']))
