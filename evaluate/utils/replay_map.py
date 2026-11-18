"""Rewrite the map path recorded in a `.replay` initial save.

A replay stores the map location it was recorded with. Micro runs used to record an absolute path
to the generated `map.tmx`, so moving the run directory (for example with `collect_runs.py`) left
that path dangling and the game aborted map loading with a "quit?" dialog even though the replay
was complete. Non-official maps are now recorded as `/SD/rustedWarfare/maps/<file>`, which the
engine resolves from `<data dir>/mods/maps/` and which therefore survives the move; maps shipped
inside `assets` keep their absolute path.

This module rewrites only that string: it decompresses the `saveCompression` block, replaces the
`mapPath` UTF value, recompresses it and fixes the block lengths. Commands, checksums, timing and the
rest of the save are byte-identical.
"""

from __future__ import annotations

import gzip
import os
import struct
import sys
from pathlib import Path

_UTILS = Path(__file__).resolve().parent
if str(_UTILS) not in sys.path:
    sys.path.insert(0, str(_UTILS))

from replay import SAVE_MAGIC, _Reader, _read_block, encode_modified_utf8  # noqa: E402

REPLAY_MAGIC = "rustedWarfareReplay"
#: Where the engine looks for non-official maps: `/SD/rustedWarfare/maps/` resolves to
#: `<data dir>/mods/maps/` (`DesktopPlatformStorage.mapsDir`), so this abstract form survives moving
#: the run directory to another machine — unlike an absolute Windows path.
MAPS_ABSTRACT_DIR = "/SD/rustedWarfare/maps/"


class ReplayMapError(ValueError):
    """The replay is not a supported container or its saved map path cannot be rewritten."""


def _utf_bytes(text: str) -> bytes:
    encoded = encode_modified_utf8(text)
    return struct.pack(">H", len(encoded)) + encoded


def _block(name: str, payload: bytes) -> bytes:
    return _utf_bytes(name) + struct.pack(">i", len(payload)) + payload


def _read_container(data: bytes) -> tuple[bytes, list[tuple[str, bytes]]]:
    reader = _Reader(data)
    if reader.utf() != REPLAY_MAGIC:
        raise ReplayMapError("not a rustedWarfareReplay container")
    reader.int()
    reader.int()
    reader.utf()
    reader.boolean()
    header = data[: reader.pos]
    blocks: list[tuple[str, bytes]] = []
    while not reader.eof():
        name = reader.utf()
        blocks.append((name, reader.take(reader.int())))
    return header, blocks


def _map_path_from_save(payload: bytes) -> str:
    reader = _Reader(payload)
    if reader.utf() != SAVE_MAGIC:
        raise ReplayMapError("gamesave block does not start with rustedWarfareSave")
    reader.int()
    reader.int()
    reader.boolean()
    name = reader.utf()
    if name != "saveCompression":
        raise ReplayMapError(f"unexpected save block: {name!r}")
    compressed = reader.take(reader.int())
    try:
        body = gzip.decompress(compressed)
    except OSError as exc:
        raise ReplayMapError(f"saveCompression is not readable gzip: {exc}") from exc
    rest = _Reader(body)
    for expected in ("customUnitsBlock", "gameSetup"):
        found, _ = _read_block(rest, "save")
        if found != expected:
            raise ReplayMapError(f"unexpected save layout: expected {expected!r}, found {found!r}")
    return rest.utf()


def _rewrite_save(payload: bytes, map_path: str) -> tuple[bytes, str]:
    reader = _Reader(payload)
    if reader.utf() != SAVE_MAGIC:
        raise ReplayMapError("gamesave block does not start with rustedWarfareSave")
    reader.int()
    reader.int()
    reader.boolean()
    name = reader.utf()
    if name != "saveCompression":
        raise ReplayMapError(f"unexpected save block: {name!r}")
    size_offset = reader.pos
    compressed = reader.take(reader.int())
    try:
        body = gzip.decompress(compressed)
    except OSError as exc:
        raise ReplayMapError(f"saveCompression is not readable gzip: {exc}") from exc
    rest = _Reader(body)
    for expected in ("customUnitsBlock", "gameSetup"):
        found, _ = _read_block(rest, "save")
        if found != expected:
            raise ReplayMapError(f"unexpected save layout: expected {expected!r}, found {found!r}")
    prefix = body[: rest.pos]
    old_path = rest.utf()
    suffix = body[rest.pos:]
    rebuilt = gzip.compress(prefix + _utf_bytes(map_path) + suffix, compresslevel=6, mtime=0)
    return payload[:size_offset] + struct.pack(">i", len(rebuilt)) + rebuilt, old_path


def replay_map_path(replay: Path) -> str:
    """Return the absolute map path recorded in the replay's initial save."""
    _, blocks = _read_container(replay.read_bytes())
    for name, payload in blocks:
        if name == "gamesave":
            return _map_path_from_save(payload)
    raise ReplayMapError("replay has no gamesave block")


def patch_bytes(data: bytes, map_path: str) -> tuple[bytes, str]:
    """Return (patched replay bytes, previous map path)."""
    header, blocks = _read_container(data)
    out: list[bytes] = []
    previous: str | None = None
    for name, payload in blocks:
        if name == "gamesave" and previous is None:
            payload, previous = _rewrite_save(payload, map_path)
        out.append(_block(name, payload))
    if previous is None:
        raise ReplayMapError("replay has no gamesave block")
    return header + b"".join(out), previous


def _same_path(left: str, right: Path) -> bool:
    try:
        return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(right.resolve()))
    except OSError:
        return False


def stored_map_reference(map_file: Path, stored_name: str | None = None) -> str:
    """Return the form a replay should record for `map_file`.

    Official maps live inside the packaged assets and keep their absolute path; every other map is
    served from the engine's `mods/maps` directory, so the abstract `/SD/rustedWarfare/maps/<file>`
    path is written instead. It resolves to `<data dir>/mods/maps/<file>` on any machine, which is
    what makes a copied run directory playable again. `stored_name` overrides the recorded file name
    for generated maps that would otherwise all be called `map.tmx`.
    """
    resolved = map_file.resolve()
    if "assets" in [part.lower() for part in resolved.parts]:
        return str(resolved)
    return MAPS_ABSTRACT_DIR + (stored_name or resolved.name)


def patch_replay(replay: Path, map_file: Path, apply: bool = True,
                 stored_name: str | None = None) -> dict[str, object]:
    """Point one replay at `map_file`. Returns a plan/result dict; writes atomically when apply."""
    absolute = map_file.resolve()
    if not absolute.is_file():
        raise ReplayMapError(f"map file does not exist: {absolute}")
    reference = stored_map_reference(absolute, stored_name)
    data = replay.read_bytes()
    patched, previous = patch_bytes(data, reference)
    changed = previous.replace("\\", "/").casefold() != reference.casefold()
    result = {
        "replay": str(replay),
        "previousMap": previous,
        "map": reference,
        "mapFile": str(absolute),
        "changed": changed,
    }
    if changed and apply:
        temporary = replay.with_name(replay.name + ".tmp")
        temporary.write_bytes(patched)
        temporary.replace(replay)
        result["applied"] = True
    else:
        result["applied"] = False
    return result
