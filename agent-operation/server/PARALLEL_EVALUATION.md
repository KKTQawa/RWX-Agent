# Parallel evaluation runs

For the separate automatic-recording micro-evaluation workflow, use [PARALLEL_MICRO_EVALUATION.md](PARALLEL_MICRO_EVALUATION.md); this document is for full matches.

Each measured match has one directory outside the checkout. The directory is the match boundary: its port, player preferences, replay, command log, engine evidence and Agent scratch files never overlap another match.

## Start one run

Build the runtime once after code changes, then create a new run directory. Do not reuse an existing run directory.

```powershell
Set-Location X:\game\RWX
.\gradlew.bat :desktop:headlessDist
.\agent-operation\server\start-evaluation-run.ps1 -Run X:\game\RWX-multiagent\run-007 `
    -Headless:$false -CommandCenterWinCondition:$true

rwx rwx-skirmish
rwx rwx-game-map-show --spawns
rwx rwx-battleroom-start --record
rwx rwx-game-state --summary
rwx rwx-game-surrender
rwx rwx-game-replay-status
rwx rwx-game-abort
rwx rwx-exit
```

Both switches default to `$true`, so the two arguments above are explicit documentation rather than a requirement. `-Headless:$false` (or the older `-Window`) opens a visible client; `-CommandCenterWinCondition:$false` restores the map's own victory condition (stock skirmish: a team loses when it has no builder or mobile unit left). The launcher appends `--headless` and/or `--win-condition=commandCenter` to the game arguments.

The command waits for `rwx-ping`, then prints the exact sentence to give the Agent. Start a separate process for every additional run; each call requires a distinct, initially absent directory. The printed object also reports the effective `Headless` and `WinCondition` values.

A visible client (`-Headless:$false` or `-Window`) additionally opens a **client terminal** in the run
directory: `<run>\rwx-shell.ps1`, where `rwx <命令>` and a `play <地图> [-Difficulty <难度>]` shortcut are
defined. That window is only a CLI client — closing it does not touch the game process, the replay or the
engine evidence, so materials keep accumulating and `collect-evaluation-run.ps1` still works. Pass
`-NoTerminal` to suppress it.

## Human baseline match

A human match has **no `commands-<match>.txt`** (mouse orders never reach the CLI recorder), so Stage1-v2 —
which approximates the Agent's reaction cadence from its commands — is not evaluated: the pipeline writes
`stage_1_v2/score.json` with `score: 0` and `human: true`, and `total-v2.1 = 0.4×0 + 0.6×stage3`.
Everything else (Stage3-v2 / v2.1, the ledger, match ids) is unchanged, and the web page shows the row under
「人类」. The match must be started with `--evaluate` (engine evidence on) or there is nothing to score.

One command, straight into a recorded match (`-Map` accepts a display name or file name; `-ListMaps` prints
the candidates under `<repo>\mods\maps`):

```powershell
.\agent-operation\server\start-evaluation-run.ps1 -Run X:\game\RWX-multiagent\run-001 `
    -Human -Map 'Whale_[2p]_[By Tstis]' -Difficulty medium
```

`-Human` implies a visible client, copies just that `.tmx` (plus `_map.png`) into `<run>\mods\maps` — the
game only lists maps that physically sit there — opens the client terminal, and drives
`rwx-skirmish` → `rwx-battleroom-select-map` → `rwx-battleroom-add-ai` → `rwx-battleroom-start --record`
so the replay starts at tick 0. Then play with the mouse. Without `-Human`/`-Map` the same flow can be typed
in the terminal (`play '<地图>' [-Difficulty hard]`); official maps are always available there, mod maps
only if the run was started with `-Map`.

**材料不全的对局不评。** A human match needs `replays/` as much as the engine evidence: without a replay the
numbers cannot be replayed for review. If a match was started without `play` / `-record` (game log shows
`recording: false`), `collect-evaluation-run.ps1` refuses it, and `evaluate_corpus_v2.js` reports
`human_missing_replay` — re-play the match instead of scoring it.

After the match:

```powershell
.\agent-operation\server\collect-evaluation-run.ps1 -Run X:\game\RWX-multiagent\run-001 -Tool Human -Apply -Batch
```

That parses the replay without `--commands`, records Stage1 as 0, scores Stage3, writes `meta.json`
(`tools.profile=Human`, `… · 人类` display name) and rebuilds the ledger. `commands\`（开局用的 lobby 日志）
is kept as `source-run\` evidence and never scored.

## Headless versus visible clients

Headless is the default because parallel runs contend for the machine, not because a window breaks isolation. Every run already has its own directory, port, `--data-dir`, logs, command capture and evidence directory, so two clients never read each other's state regardless of the render backend.

A visible client adds four things to watch when more than one window is open:

- **Focus and input.** Only the focused window receives keyboard and mouse. Agents issue everything through `<run>\rwx.cmd`, so their commands are unaffected, but manual clicks and hotkeys can land in the wrong match. Do not drive two windows by hand at the same time.
- **Overlap and identity.** Windows open at the default position and would share the title `RWX Game`; the launcher stamps `RWX-<run directory name>` into `-Drwx.windowTitle` so two windows can be told apart, but they still stack on top of each other. Identify a match by its run directory and `logs\`, and position the windows apart before starting if you need to watch several.
- **Occlusion throttling.** A fully covered or minimised window may be throttled or stopped by the compositor or driver; at best that makes realtime timing (cadence, action delay) unreliable, at worst the match stalls. Keep watched windows uncovered and never minimised.
- **GPU, audio and memory.** Each visible client creates its own OpenGL context, loads textures and opens an audio device; headless skips rendering and audio entirely (it still uses normal JVM heap). Four or more visible clients can exhaust VRAM and make every instance slower, which is exactly the kind of noise the realtime tier exists to avoid.

Use visible clients for one or two runs that a human is supervising, and headless for everything else. Never start two clients against the same run directory: the launcher refuses an existing directory.

## Give the Agent only its boundary

Provide the prompt template in [`../prompt_single.md`](../prompt_single.md), replacing `{{RUN}}` with the printed run directory. The Agent starts by reading [`../START.md`](../START.md), issues every game command through `<run>\rwx.cmd`, and stores only its own scripts and notes in `<run>\tmp`.

The Agent does not need to read any port or evidence file. `rwx.cmd` is bound to `<run>\port`; the wrapper also exposes the Python client's `--stdio` and `--batch-file` modes without exposing a shared endpoint.

## Ownership map

| Path under `<run>` | Owner | Agent rule |
|---|---|---|
| `rwx.cmd`, `port`, `events-port` | launcher/runtime | Invoke `rwx.cmd`; do not edit or select ports manually. |
| `tmp/` | Agent | Read/write its own scripts, logs and batch files only. |
| `replays/`, `commands/`, `events-live/`, `logs/` | game/runtime | Produced by the match; do not delete, rename or write them. |
| `preferences.toml` and other game state | game/runtime | Do not edit during a measured match. |

The repository's `agent-operation/tmp`, `agent-tmp` and `replays` are legacy single-instance locations. They are neither inputs nor outputs of a parallel evaluation run. `evaluate/output/` is different: it is the evaluation batch, and a finished run is imported into it deliberately (next section).

## Collect a finished run

One finished run is imported and scored with one command:

```powershell
# dry run: prints the match name it would use and the materials it would move
.\agent-operation\server\collect-evaluation-run.ps1 -Run X:\game\RWX-multiagent\run-003 -Tool Pi
# import + parse replay + preprocess + score + write meta.json
.\agent-operation\server\collect-evaluation-run.ps1 -Run X:\game\RWX-multiagent\run-003 -Tool Pi -Apply
```

`-Tool` picks the directory slug and the `meta.json` tool label (`Pi`, `CommandCode`, `DSH`, `Codex`,
`Claude Code`, `OpenChamber`, `OpenCode v2`). The script names the match
`<map>-<yyyyMMdd>--<HH-mm>_<tool-slug>` from the telemetry map name and the command-log stamp, moves
`commands/`, `events-live/` and `replays/` into place, keeps the rest of the run as `source-run/`, deletes
the emptied run directory, then prints the outcome and the remaining batch steps.

`-OutRoot <dir>` puts the match somewhere else (score a run **without** touching `evaluate/output`, so the
ledger and the match numbering stay untouched); pair it with the `--match` scoring command below and delete
the copy afterwards — it duplicates the telemetry.

After one or more matches are imported, finish the batch:

```powershell
node evaluate/tools/evaluate_corpus_v2.js --current      # re-scores every current match, writes _v2-summary.json
node evaluate/tools/add_v21_scores.js --current-only     # refreshes _v21-summary.json
node evaluate/tools/build_web_results_v2.js              # updates web/resource/results.json
python web/tools/build_match_ids.py                      # assigns M-ids and writes meta.json.matchId
python web/tools/check_site.py                           # asserts ledger, ids and meta agree
```

Doing it by hand (same steps the script performs) — scoring reads one directory per match. A run already holds the three materials, just under the names the runtime wrote, so the import is a move into the canonical layout:

| From `<run>` | To `evaluate/output/<match>/` |
|---|---|
| `commands\commands-<map>-<stamp>.txt` | `commands-<match>.txt` |
| `events-live\match-…\` | `events-live\<match>\` |
| `replays\*.replay` | `replay\<match>.replay` |
| `logs\`, `mods\`, `saves\`, `tmp\`, `preferences.toml`, `p2p.toml`, locks | `source-run\` (kept as evidence) |

`<match>` follows the batch convention `<map>-<yyyyMMdd>--<HH-mm>_<tool>`. Then:

```powershell
$m = "evaluate/output/<match>"
python evaluate/utils/replay.py "$m/replay/<match>.replay" --commands "$m/commands-<match>.txt"
node evaluate/preprocess.js "$m"
node evaluate/tools/match_materials.js --apply --match "<match>" `
    --set model=deepseek-v4.1-flash --set provider=opencode --set thinking=high --set tool=CommandCode
```

…然后按上面的批量收尾命令跑 `--current` / `add_v21_scores` / `build_web_results_v2` /
`build_match_ids` / `check_site`。注意 PowerShell 的 `Move-Item`/`Test-Path` 会把 `[2p]` 当通配符，
手工搬材料时用 `-LiteralPath`。

`evaluate_corpus_v2.js --match <dir>` re-scores a single match but rewrites `_v2-summary.json` with only that row, so always finish with `--current`.

## Human baseline match (collecting)

The play side is in [Human baseline match](#human-baseline-match) above. Once the human match is over, one
command collects it — it takes the newest `X:\game\RWX-multiagent\run-*`, imports the materials, scores
Stage3, and rebuilds the page:

```powershell
.\agent-operation\server\collect-evaluation-run.ps1 -Tool Human -Apply -Batch
```

Pass `-Run <目录>` to pick a specific run, drop `-Batch` to only score without rebuilding the ledger, and
add `-OutRoot <目录>` to evaluate without publishing. The replay is parsed without `--commands`, and
`meta.json` gets `tools.profile=Human` plus a `… · 人类` display name, which is what puts the row on the
「人类」line. The `commands\` folder of a human run holds only the lobby log (`rwx-ping`, `rwx-battleroom-*`);
it is kept under `source-run\` as evidence and never scored.

A run that must **not** enter the public ledger is scored in a throwaway copy instead: build the same `<match>/{commands-<match>.txt, events-live/<match>, replay/, prepared/, stage_3/, score_v2.json, score_v21.json}` layout under `X:\game\RWX-multiagent\evaluated\<match>\` and score it with `node evaluate/tools/evaluate_corpus_v2.js --match <that dir>`. Nothing under `evaluate/output/` changes, so the ledger and the match numbering stay untouched; run `evaluate_corpus_v2.js --current` afterwards to restore the batch summary. That copy duplicates the telemetry (hundreds of MB per match), so delete it once the numbers are written down and keep only a short summary next to the run directories.

## Evidence and recovery

The launcher passes an explicit port, evidence directory, command-capture directory and log directory to the game. Replays remain under `<run>\replays` because the process working directory and `--data-dir` are both `<run>`.

If readiness times out, retain the run unchanged and inspect `logs\game.stdout.log` and `logs\game.stderr.log`. Do not point an Agent at another run or substitute a repository-level port file.
