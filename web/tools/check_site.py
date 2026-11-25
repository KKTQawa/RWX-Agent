"""Validate deployable site paths, recording integrity, ledger data and GitHub size limits."""

import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        for name in ('src', 'href', 'poster'):
            if attrs.get(name):
                self.links.append(attrs[name])


def parse(name):
    page = Page()
    page.feed((WEB / name).read_text(encoding='utf-8'))
    assert len(page.ids) == len(set(page.ids)), 'Duplicate page IDs in ' + name
    for link in page.links:
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc:
            continue
        if parsed.path:
            target = (WEB / unquote(parsed.path)).resolve()
            assert target.is_relative_to(WEB), 'A site asset escapes web/: ' + link
            assert target.is_file(), 'Missing site asset: ' + link
        elif parsed.fragment:
            assert parsed.fragment in page.ids, 'Missing page anchor in ' + name + ': ' + link
    return page


def check_ledger():
    data = json.loads((WEB / 'resource/results.json').read_text(encoding='utf-8'))
    assert data['schema'] == 3
    standard = data['standard']
    assert standard['version'] == 'total-v2'
    assert 0 <= standard['k'] <= 1
    matches = data['matches']
    assert len(matches) == data['overview']['matches'] >= 1
    assert len({item['id'] for item in matches}) == len(matches)
    ids = {item['id'] for item in matches}
    assert data['overview']['best']['id'] in ids
    for item in matches:
        for key in ('title', 'archive', 'date', 'result', 'scores', 'pairs', 'duration', 'stage3', 'v21', 'fluency'):
            assert key in item, f'{item["id"]}: missing {key}'
        assert item['archive'] == 'current'
        assert item['duration']['scoreSeconds'] > 0
        assert item['result']['outcome'] in {'win', 'defeat', 'draw', 'unknown'}
        assert isinstance(item.get('scriptAi'), bool) and isinstance(item.get('human'), bool)
        assert item['pairs']
        for pair in item['pairs']:
            assert pair['agent']['model'] and pair['agent']['provider'] and pair['agent']['reasoning']
            assert pair['tool']['name'] and 'extra' in pair['tool']
        # 操作流畅度四元组：流畅度 / μ / q / CV。附加分，不进总分；三个分量必须有值，CV 允许
        # 因窗口不足为空，但字段本身必须存在。
        fluency = item['fluency']
        assert fluency and fluency['appliesToTotal'] is False, item['id'] + ': fluency must be an add-on'
        assert fluency['material'] in {'native', 'live'}, item['id'] + ': unknown fluency material'
        assert 0 <= fluency['score'] <= 100, item['id'] + ': fluency score out of range'
        assert isinstance(fluency['mu'], (int, float)), item['id'] + ': fluency mu missing'
        assert isinstance(fluency['dead'], (int, float)), item['id'] + ': fluency dead share missing'
        assert fluency['cv'] is None or isinstance(fluency['cv'], (int, float)), item['id'] + ': fluency cv invalid'
        scores = item['scores']
        expected = max(0.0, min(100.0, scores['stage1V2'] - (100 - scores['stage3']) * (1 - standard['k'])))
        assert abs(scores['totalV2'] - expected) < 0.01, item['id'] + ': total-v2 does not match the stage1-v2 minus Stage3-shortfall formula'
        for name in ('totalV2', 'stage1V2', 'stage3'):
            assert 0 <= scores[name] <= 100
        assert set(item['stage3']['deductions']) == {'STAGE3_AMBUSH', 'STAGE3_BARRAGE', 'STAGE3_GRINDER', 'STAGE3_FUNDS'}
    v21_standard = data['standard21']
    assert v21_standard['version'] == 'total-v2.1'
    assert v21_standard['stage3'] == 'stage3-score-v2.1-v3'
    weights = v21_standard['weights']
    caps = v21_standard['caps']
    assert abs(weights['stage1'] + weights['stage3'] - 1) < 1e-9
    assert set(caps) == {'ambush', 'barrage', 'grinder', 'funds'}
    for item in matches:
        v21 = item['v21']
        assert v21 is not None, item['id'] + ': current matches need a v2.1 block'
        for key in ('total', 'stage1', 'stage3', 'delta', 'items', 'v2'):
            assert key in v21, f'{item["id"]}: v21 missing {key}'
        assert set(v21['items']) == {'ambush', 'barrage', 'grinder', 'funds'}
        for key, value in v21['items'].items():
            assert abs(value['cap'] - caps[key]) < 1e-9, f'{item["id"]}: {key} cap mismatch'
            assert 0 <= value['deduction'] <= value['cap'] + 1e-6, f'{item["id"]}: {key} deduction out of range'
        total = max(0.0, min(100.0, weights['stage1'] * v21['stage1'] + weights['stage3'] * v21['stage3']))
        assert abs(v21['total'] - total) < 0.01, item['id'] + ': total-v2.1 does not match the weighted stage formula'
        shortfall = sum(value['deduction'] for value in v21['items'].values())
        assert abs(v21['stage3'] - max(0.0, 100 - shortfall)) < 0.02, item['id'] + ': stage3-v2.1 does not match 100 minus deductions'
        assert abs(v21['delta'] - (v21['total'] - v21['v2']['total'])) < 0.01, item['id'] + ': delta must be total-v2.1 minus total-v2'
    overview21 = data['overview21']
    assert overview21['matches'] == len(matches)
    totals = [item['v21']['total'] for item in matches]
    assert abs(overview21['average'] - round(sum(totals) / len(totals), 3)) < 0.01
    assert overview21['best']['id'] in ids
    ignored = data['ignored']
    assert len(ignored) == data['overview']['ignored'], 'ignored count must match the current v2 page'
    titles = {item['title'] for item in matches}
    for item in ignored:
        assert item['title'] and item['reason'] and item['note'] and item['relativePath']
        assert item['title'] not in titles, 'a match cannot be both ranked and ignored'
    assert data['method']['limits'], 'known limits must be recorded'
    # Two scoring systems live on the page: v2.1 (current) and v2 (comparison), plus a frozen v1 snapshot.
    v1 = data['v1']
    assert v1['version'] == 'total-v1' and v1['frozen'] is True
    assert v1['weights'] == {'stage1': 0.4, 'stage2': 0.6}
    assert len(v1['stage1']['caps']) == len(v1['stage1']['names']) == 12
    assert set(v1['stage2']['caps']) == {'AMBUSH', 'GRINDER', 'STALE', 'BUILDER_IDLE', 'FACTORY_IDLE', 'FUNDS'}
    v1_matches = v1.get('matches', [])
    scored = [item for item in v1_matches if item['scores']['totalV1'] is not None]
    assert len(scored) == v1['counts']['scored']
    for item in scored:
        expected = item['scores']['stage1V1'] * 0.4 + item['scores']['stage2'] * 0.6
        assert abs(item['scores']['totalV1'] - expected) < 0.01, item['id'] + ': total-v1 does not match weighted stages'
    assert data['overview']['archives'] == {}
    return data


def check_scoring():
    data = json.loads((WEB / 'resource/scoring.json').read_text(encoding='utf-8'))
    assert data['schema'] == 2
    stages = data['fullMatch']['stages']
    # Only the standard that is actually in force may be published: Stage1-v2 and Stage3-v2.1.
    assert [stage['id'] for stage in stages] == ['stage1', 'stage3v21']
    assert [stage['role'] for stage in stages] == ['current', 'current']
    assert len(stages[0]['items']) == 4, 'Stage 1-v2 must list 3 groups plus the activity gate'
    assert len(stages[1]['items']) == 4, 'Stage 3-v2.1 must list all 4 deduction families'
    assert stages[0]['notes'], 'Stage 1-v2 must record its provisional caveats'
    v21 = data['fullMatch']['v21']
    assert v21['version'] == 'stage3-score-v2.1-v3' and v21['total'] == 'total-v2.1'
    assert abs(v21['weights']['stage1Weight'] + v21['weights']['stage3Weight'] - 1) < 1e-9
    for group in stages:
        assert group['version'] and group['items']
        for item in group['items']:
            assert item['name'] and item['formula'] and item['description']
            assert item['cap'] > 0
    return data


def check_match_ids(ledger):
    """Every current match carries exactly one stable code; archived runs carry none."""
    data = json.loads((WEB / 'resource/match-ids.json').read_text(encoding='utf-8'))
    assert data['schema'] == 1
    codes = data['matches']
    current = {item['id'] for item in ledger['matches'] if item['archive'] == 'current'}
    assert set(codes) == current, 'match-ids.json must cover exactly the current match batch'
    values = list(codes.values())
    assert len(values) == len(set(values)), 'match ids must be unique'
    for code in values:
        assert re.fullmatch(r'M\d{2,}', code), 'match id must look like M01: ' + code
    # The material directory carries the same code in its meta.json; a mismatch means one side was
    # regenerated without the other and the page would show a number the evidence does not have.
    for item in ledger['matches']:
        if item['archive'] != 'current' or not item.get('path'):
            continue
        meta_file = ROOT / 'evaluate' / 'output' / item['path'] / 'meta.json'
        assert meta_file.is_file(), 'missing meta.json for ' + item['path']
        meta = json.loads(meta_file.read_text(encoding='utf-8'))
        assert meta.get('matchId') == codes[item['id']],             'meta.json matchId mismatch for ' + item['path'] + ': ' + str(meta.get('matchId'))
    return data


def check_micro():
    """CASE records, rules and time comparisons must come from the runs, never a second list."""
    data = json.loads((WEB / 'resource/micro-results.json').read_text(encoding='utf-8'))
    assert len(data['cases']) == 4
    for case in data['cases']:
        mode = case.get('displayMode', 'score')
        assert mode in {'score', 'time', 'time-seed'}, case['case'] + ': unknown display mode'
        assert case['task'] and case['records'], case['case'] + ': needs a task and records'
        assert case['environment'] and case['imageAlt'] and case['imageCaption']
        image = (WEB / case['image'].removeprefix('./')).resolve()
        assert image.is_relative_to(WEB) and image.is_file(), 'Missing CASE image: ' + case['image']
        if mode == 'score':
            assert case['items'], case['case'] + ': score cases need rules'
            caps = {item['id']: item['cap'] for item in case['items']}
            for record in case['records']:
                assert record['kindLabel'] and record['note'], case['case'] + ': record needs a label and a note'
                assert isinstance(record['score'], (int, float))
                assert set(record['items']) == set(caps), case['case'] + ': every record must cover every rule'
                total = 0.0
                for key, value in record['items'].items():
                    assert abs(value['cap'] - caps[key]) < 1e-9, f"{case['case']}/{key}: cap differs from the rule table"
                    assert value['points'] is not None and 0 <= value['points'] <= caps[key] + 1e-6
                    total += value['points']
                assert abs((100 - total) - record['score']) < 0.15, case['case'] + ': item points must sum to the score'
            for record in [item for item in case['records'] if item['kind'] == 'agent']:
                if case['case'] == 'CASE4-Retreat':
                    meta = json.loads((ROOT / record['source'] / record['run'] / 'meta.json').read_text(encoding='utf-8'))
                    assert record['kindLabel'] == re.sub(r'[^a-z0-9.]+', '-', meta['models'][0]['id'].lower()).strip('-')
                    assert record['thinking'] == meta['models'][0]['thinking']
                    assert meta['tools'][0]['profile'] in record['detail']
                else:
                    assert record['kindLabel'] == 'deepseek-v4.1-flash', f"{case['case']}: agent label must be the model id"
                    assert record['detail'] and record['detail'].split(' ')[0] in {'Pi', 'DSH'}, f"{case['case']}: agent row must name its tool"
            if case['case'] == 'CASE4-Retreat':
                for record in case['records']:
                    run = ROOT / record['source'] / record['run']
                    meta = json.loads((run / 'meta.json').read_text(encoding='utf-8'))
                    result = json.loads((run / 'result.json').read_text(encoding='utf-8'))
                    assert (record['seed'], record['layoutVersion']) == (meta['seed'], meta['layoutVersion'])
                    assert record['casualties']['selfTotal'] - record['casualties']['selfLost'] == result['tanksAlive']
            if case['case'] == 'CASE1-duel':
                # CASE1 的伤亡列：我方损失 / 敌方损失 + 逐单位 HP/护盾与承伤比例。
                for record in case['records']:
                    casualties = record.get('casualties')
                    assert casualties, 'CASE1 rows need casualties'
                    for key in ('selfLost', 'selfTotal', 'enemyLost', 'enemyTotal'):
                        assert isinstance(casualties.get(key), int), 'CASE1 casualties missing ' + key
                    assert 0 <= casualties['selfLost'] <= casualties['selfTotal']
                    assert 0 <= casualties['enemyLost'] <= casualties['enemyTotal']
                    assert isinstance(casualties.get('selfUnits'), list)
                    for unit in casualties['selfUnits']:
                        for key in ('hp', 'maxHp', 'shield', 'maxShield', 'damage'):
                            assert isinstance(unit.get(key), (int, float)), 'CASE1 unit missing ' + key
                        assert 0 <= unit['hp'] <= unit['maxHp'], 'CASE1 unit HP out of range'
                        assert 0 <= unit['shield'] <= unit['maxShield'], 'CASE1 unit shield out of range'
                        assert unit.get('damageRatio') is None or 0 <= unit['damageRatio'] <= 1
                    assert isinstance(casualties.get('selfDamage'), (int, float))
                    assert isinstance(casualties.get('selfCapacity'), (int, float)) and casualties['selfCapacity'] > 0
                    assert 0 <= casualties['selfDamageRatio'] <= 1
        else:
            # CASE02/03 compare duration against the same task's script baseline; the score is retired.
            assert case['items'] == [], case['case'] + ': time cases must not publish the old rule table'
            assert case['tasks'] and all(case['tasks'])
            for record in case['records']:
                assert record['kind'] in {'baseline', 'agent', 'human'}
                assert record['kindLabel'] and record['task'], case['case'] + ': time row needs a label and task id'
                assert isinstance(record['seconds'], (int, float)) and record['seconds'] > 0
                assert record['timeout'] in {True, False}
                assert record['baselineSeconds'] is None or isinstance(record['baselineSeconds'], (int, float))
                if record['kind'] != 'baseline':
                    assert isinstance(record['baselineSeconds'], (int, float)), \
                        case['case'] + ': every non-baseline row needs the same-task baseline time'
                if mode == 'time-seed':
                    assert record['seed'] is not None, case['case'] + ': time-seed rows need a seed'
    return data



if __name__ == '__main__':
    page = parse('index.html')
    html = (WEB / 'index.html').read_text(encoding='utf-8')
    assert '<title>RWX-Agent：让智能体参与经典RTS游戏Rusted Warfare</title>' in html
    assert 'https://github.com/KKTQawa/RWX-Agent' in html
    assert 'https://github.com/yomi2539/RWX' in html
    assert '并定期同步上游源码' in html

    ledger_page = parse('results.html')
    ledger_html = (WEB / 'results.html').read_text(encoding='utf-8')
    assert ledger_page.ids, 'Ledger page must expose anchor targets'
    assert '<title>评测观察｜RWX-Agent</title>' in ledger_html
    assert 'id="case-board"' in ledger_html
    assert 'id="match-table-body"' in ledger_html, 'Ledger page must render matches into a table body'
    assert 'id="overview-matrix-body"' in ledger_html, 'Ledger page must expose the overview matrix'
    assert 'class="data-table match-ledger-table"' in ledger_html, 'Ledger matches must use the data table'
    assert ledger_html.count('data-deduction-key=') == 4, 'Ledger table must expose all four Stage3 deduction columns'
    assert '现有结论' in ledger_html, 'The findings panel must be titled 现有结论'
    assert '资金 v2' in ledger_html, 'The ledger must show the funds-v2 column instead of the delta'
    assert 'Δ vs v2' not in ledger_html, 'The old delta column must be gone'
    assert '模型决定胜负' in ledger_html and '工具影响实时' in ledger_html, 'Ledger must carry the thesis line'
    for key in ('ambush', 'barrage', 'grinder', 'funds'):
        assert f'data-deduction-key="{key}"' in ledger_html, 'Missing deduction column: ' + key
    ledger_js = (WEB / 'results.js').read_text(encoding='utf-8')
    for asset in ('resource/results.json', 'resource/scoring.json', 'resource/micro-results.json', 'resource/match-ids.json'):
        assert asset in ledger_js, 'results.js must read ' + asset
    assert 'overview21' in ledger_js and 'v21' in ledger_js, 'results.js must render the v2.1 ledger'
    assert 'overview-matrix-body' in ledger_js, 'results.js must render the overview matrix'
    assert 'matrix-fluency' in ledger_js and 'fluency-cell' in ledger_js, 'results.js must render the fluency tuple'
    assert 'MATRIX_SCRIPT' in ledger_js, 'results.js must give the script baseline its own matrix row'
    assert 'matrix-pin' in ledger_js and 'fitMatrixPins' in ledger_js, 'results.js must freeze the matrix columns'
    assert 'bindMatrixResize' in ledger_js and 'matrix-resize-handle' in ledger_js, 'results.js must make the matrix height draggable'
    assert 'case-time' in ledger_js and 'caseTimePanel' in ledger_js, 'results.js must render CASE time comparisons'
    assert ledger_html.count('class="fluency-column"') == 1, 'The ledger needs exactly one fluency column'
    assert (WEB / 'results.js').is_file()

    optimization_page = parse('optimization.html')
    optimization_html = (WEB / 'optimization.html').read_text(encoding='utf-8')
    assert '<title>黑盒优化｜RWX-Agent</title>' in optimization_html
    assert optimization_page.ids, 'Optimization page must expose anchor targets'
    for section in ('id="dimension-table"', 'id="dimension-groups"', 'id="reward-table"',
                    'id="reward-v1"', 'id="reward-v2"', 'id="reward-v3"', 'id="ceiling-table"'):
        assert section in optimization_html, 'Optimization page is missing ' + section
    assert '70.0%' in optimization_html, 'Optimization page must state the measured Hard-up v1 ceiling'
    assert './results.html' in optimization_html, 'Optimization page must link back to the ledger'
    assert './optimization.html' in html, 'Home page must link to the optimization page'
    assert './optimization.html' in ledger_html, 'Ledger page must link to the optimization page'
    assert '模型决定胜负' in html and '工具影响实时' in html, 'Landing page must carry the thesis line'
    assert (WEB / 'theme.js').is_file()
    for page in (html, ledger_html, optimization_html):
        assert 'theme.js' in page and 'class="theme-toggle"' in page, 'every page needs the theme toggle'
    assert './results.html' in html, 'Home page must link to the ledger'
    for section in ('id="catalog"', 'id="progress"', 'id="voices"', 'id="start"'):
        assert section in html, 'Landing page is missing ' + section

    micro = check_micro()

    recordings = json.loads((WEB / 'resource/matches.json').read_text(encoding='utf-8'))
    assert len(recordings) == 4
    assert len({item['id'] for item in recordings}) == 4
    for item in recordings:
        video = WEB / item['video']
        assert video.stat().st_size == item['bytes'], 'Video size mismatch: ' + item['id']
        assert video.stat().st_size < 100 * 1024 * 1024, 'Video exceeds GitHub limit'
        assert hashlib.sha256(video.read_bytes()).hexdigest() == item['sha256'], 'Video checksum mismatch: ' + item['id']
        assert (WEB / item['poster']).is_file()
        assert item['video'] in html, 'Missing no-JavaScript video link: ' + item['id']

    ledger = check_ledger()
    scoring = check_scoring()
    match_ids = check_match_ids(ledger)

    deployed = [WEB / name for name in ('index.html', 'styles.css', 'theme.js', 'app.js', 'results.html', 'results.js',
                                        'optimization.html', 'favicon.svg', '.nojekyll',
                                        'resource/matches.json', 'resource/results.json', 'resource/micro-results.json', 'resource/scoring.json',
                                        'resource/match-ids.json')]
    for folder in ('matches', 'posters', 'cases'):
        deployed.extend(p for p in (WEB / 'resource' / folder).rglob('*') if p.is_file())
    deployed.extend(p for p in (WEB / 'resource').glob('CASE*.mp4') if p.is_file())
    total = sum(path.stat().st_size for path in deployed)
    assert total < 1_000_000_000, 'Site exceeds GitHub Pages size limit'
    scored_cases = sum(1 for case in micro['cases'] if case.get('displayMode', 'score') == 'score')
    print(f'PASS: {len(recordings)} recordings, {ledger["overview"]["matches"]} matches, '
          f'{len(match_ids["matches"])} match ids, '
          f'{ledger["v1"]["counts"]["scored"]} with v1 scores, '
          f'{scored_cases}/{len(micro["cases"])} micro cases scored (rest time-compared), '
          f'{len(deployed)} deployable files, '
          f'{total / 1024 / 1024:.1f} MiB; local links, video checksums and ledger scores valid.')
