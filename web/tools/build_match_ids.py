"""Assign stable M01..Mnn ids to the current match batch.

Only matches that are still in the current batch (``archive == "current"`` in
``results.json``) get an id; archived runs stay unnumbered. Existing assignments are
kept, so a new match only appends the next number and re-sorting the ledger never
renames anything.

    python -B web/tools/build_match_ids.py
"""

import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
LEDGER = WEB / 'resource' / 'results.json'
OUT = WEB / 'resource' / 'match-ids.json'


def load(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else default


def number_of(code):
    suffix = code[1:] if code[:1] == 'M' else ''
    return int(suffix) if suffix.isdigit() else 0


def main():
    ledger = load(LEDGER)
    previous = load(OUT, {}) or {}
    current = [match for match in ledger['matches'] if match.get('archive') == 'current']
    current_ids = {match['id'] for match in current}

    # A match that left the current batch (archived) keeps no id.
    assigned = {key: code for key, code in (previous.get('matches') or {}).items() if key in current_ids}
    highest = max((number_of(code) for code in assigned.values()), default=0)
    fresh = sorted(
        (match for match in current if match['id'] not in assigned),
        key=lambda match: (match.get('date') or '', match['id']),
    )
    for match in fresh:
        highest += 1
        assigned[match['id']] = f'M{highest:02d}'

    payload = {
        'schema': 1,
        'note': '当前批次完整对局的稳定编号；归档对局不分配。由 web/tools/build_match_ids.py 生成，不要手改。',
        'matches': {key: code for key, code in sorted(assigned.items(), key=lambda item: (number_of(item[1]), item[0]))},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{OUT.relative_to(WEB.parent)}: {len(assigned)} current matches, {len(fresh)} newly numbered')


if __name__ == '__main__':
    main()
