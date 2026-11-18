"""Assign stable M01..Mnn ids to the current match batch.

Only matches that are still in the current batch (``archive == "current"`` in
``results.json``) get an id; archived runs stay unnumbered. Existing assignments are
kept, so a new match only appends the next number and re-sorting the ledger never
renames anything.

The same id is also written back into each match's ``meta.json`` as ``matchId`` so the
material directory carries its own number (idempotent: no write when it already matches).

    python -B web/tools/build_match_ids.py
"""

import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
ROOT = WEB.parent
LEDGER = WEB / 'resource' / 'results.json'
OUT = WEB / 'resource' / 'match-ids.json'
OUTPUT = ROOT / 'evaluate' / 'output'


def load(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else default


def number_of(code):
    suffix = code[1:] if code[:1] == 'M' else ''
    return int(suffix) if suffix.isdigit() else 0


def write_meta_ids(current, assigned):
    """Put each match id into ``evaluate/output/<path>/meta.json``; return how many changed."""
    written = 0
    for match in current:
        code = assigned.get(match['id'])
        folder = match.get('path')
        if not code or not folder:
            continue
        meta_file = OUTPUT / folder / 'meta.json'
        if not meta_file.is_file():
            continue
        meta = load(meta_file, {})
        if meta.get('matchId') == code:
            continue
        meta['matchId'] = code
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        written += 1
    return written


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
    metas = write_meta_ids(current, assigned)
    print(f'{OUT.relative_to(ROOT)}: {len(assigned)} current matches, {len(fresh)} newly numbered, '
          f'{metas} meta.json updated')


if __name__ == '__main__':
    main()
