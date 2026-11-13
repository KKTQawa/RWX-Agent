# Parallel micro evaluation runs

This is the administrator workflow for running several micro-evaluation Agents at once. It applies to all four cases
(`CASE1-duel`, `CASE2-LTE`, `CASE3-Transport`, `CASE4-Retreat`): each case ships its own managed Agent prompt and its own
lobby lifecycle. Each run keeps a live game and all of its evidence inside one external run directory; a completed micro
result is later moved into the canonical per-case archive.

## 1. Prepare and launch

Build the Headless distribution once after code changes. Allocate one previously absent directory per Agent; never reuse
a failed or completed directory.
```powershell
Set-Location X:\game\RWX
.\gradlew.bat :desktop:headlessDist

.\agent-operation\server\start-micro-evaluation-run.ps1 `
  -Run X:\game\RWX-multiagent\micro-case1-01 `
  -Case CASE1-duel `
  -CaseArgs 'task=1_2_2,seed=1331,track=realtime'
```

```powershell
Set-Location X:\game\RWX
.\gradlew.bat :desktop:headlessDist

.\agent-operation\server\start-micro-evaluation-run.ps1 `
  -Run X:\game\RWX-multiagent\micro-case2-01 `
  -Case CASE2-LTE `
  -CaseArgs 'task=2_7_4,seed=1331,track=realtime'
```

```powershell
Set-Location X:\game\RWX
.\gradlew.bat :desktop:headlessDist

.\agent-operation\server\start-micro-evaluation-run.ps1 `
  -Run X:\game\RWX-multiagent\micro-case3-01 `
  -Case CASE3-Transport `
  -CaseArgs 'task=3_3_1,seed=1331,track=realtime'
```

```powershell
Set-Location X:\game\RWX
.\gradlew.bat :desktop:headlessDist

.\agent-operation\server\start-micro-evaluation-run.ps1 `
  -Run X:\game\RWX-multiagent\micro-case4-01 `
  -Case CASE4-Retreat `
  -CaseArgs 'task=4_2_1,seed=1331,track=realtime'
```

```powershell
.\gradlew.bat :desktop:run '--args=--no-steam --evaluate CASE1-duel --case-args mode=human,task=1_2_2,seed=1'
```

```powershell
.\gradlew.bat :desktop:run '--args=--no-steam --evaluate CASE4-Retreat --case-args mode=human,task=4_2_1,seed=1'
```

Launch each additional Agent in a separate PowerShell process with a distinct `-Run`, seed and assigned task. Use one of
the four accepted `-Case` values and the parameters that case accepts:

| `-Case` | Typical `-CaseArgs` | After lobby entry |
|---|---|---|
| `CASE1-duel` | `task=1_1_3,seed=101,track=realtime` (or `track=pause`) | `phase=briefing`, then `rwx-micro-1-begin` |
| `CASE2-LTE` | `task=2_5_3,seed=101,track=realtime` | `phase=briefing`, then `rwx-micro-2-begin` |
| `CASE3-Transport` | `task=3_1_1,seed=101,track=realtime` | starts running immediately; no `begin` |
| `CASE4-Retreat` | `task=4_1_1,seed=101,track=realtime` | `phase=briefing`, then `rwx-micro-4-begin` |

`-MaxHeapMiB` defaults to 768; reduce it only after accounting for the simultaneous Java processes. The launcher owns
`out=`, so do not put it in `-CaseArgs`.

Each accepted case also reads `evaluate/micro/<CASE>/config.json` for its map/scenario defaults and its score parameters.
`-CaseArgs` wins over `run` defaults; an explicit `--micro-config <file>` can replace the whole file. Edit the file before
starting a run — there is no hot reload, and changing `map` makes the new layout incomparable with the old baseline.

The command returns only after the run-local CLI reports `rwx-micro-lobby-status` with `phase=lobby`. At that point no
scenario, Replay or micro budget exists yet. The Agent owns exactly one `rwx-micro-lobby-enter` call; that call loads the
preconfigured scenario, then the normal `RWX_MICRO_READY` marker appears (CASE3 is already running at that point). If
lobby readiness fails, retain the directory for diagnosis; do not hand it to an Agent.

## 2. Hand off one bounded instance

Give the Agent the managed prompt for its case, replacing only `{{RUN}}` with the returned run directory:

| Case | Prompt |
|---|---|
| `CASE1-duel` | [`../../evaluate/micro/CASE1-duel/prompt_single.md`](../../evaluate/micro/CASE1-duel/prompt_single.md) |
| `CASE2-LTE` | [`../../evaluate/micro/CASE2-LTE/prompt_single.md`](../../evaluate/micro/CASE2-LTE/prompt_single.md) |
| `CASE3-Transport` | [`../../evaluate/micro/CASE3-Transport/prompt_single.md`](../../evaluate/micro/CASE3-Transport/prompt_single.md) |
| `CASE4-Retreat` | [`../../evaluate/micro/CASE4-Retreat/prompt_single.md`](../../evaluate/micro/CASE4-Retreat/prompt_single.md) |

Send it together with that case's `START.md` and command manual (`commands.md` for CASE1/CASE2, `command.md` for
CASE3/CASE4). The prompt sends all commands through `<run>\rwx.cmd`; it must not disclose `CaseArgs`, port files,
evidence locations, or any other run.

The Agent may write only `<run>\tmp`. The runtime owns `logs/`, `commands/`, `events-live/`, `replays/`, and
`micro-output/`. One micro run is automatic-recording: there is no battleroom setup, manual replay recording, or
`rwx-exit` step.

## 3. Verify and evaluate one finished run

Wait for the process to exit naturally. A successful micro run has exactly one direct child of `<run>\micro-output`
containing both `meta.json` and `result.json`.

```powershell
$run = 'X:\game\RWX-multiagent\micro-case1-a01'
python -B .\evaluate\micro\collect_runs.py --run $run
python -B .\evaluate\micro\collect_runs.py --run $run --apply
```

The first command is a dry run. The second moves the completed directory into `evaluate/output/micro/<case>/` using
`meta.case` from the result; it refuses incomplete output, multiple candidates, unsafe case names, and existing
destinations. It never overwrites material. A missing replay is not recreated or guessed. The move also repoints
`meta.map.file` **and the map path stored inside the replay** at the archived `map.tmx`; without the latter the replay
opens a "quit?" dialog because its recorded map no longer exists. Legacy or manually moved replays can be repaired with
`python -B .\evaluate\tools\patch_replay_map.py --run <run> --apply`.

The archive must also contain the Agent session as `session/<session-id>.jsonl` plus a readable
`session/transcript.md`. The session is outside the engine's `micro-output`, so copy it after
collection; `meta.json` continues to point at the replay, and the evaluators never read the session.

Record the model/tool identity in the archived `meta.json` (the engine does not know it):

```powershell
python -B .\evaluate\tools\stamp_micro_meta.py --run .\evaluate\output\micro\<case>\<run> `
  --provider OpenCode --model "DeepSeek V4.1 Flash" --thinking high --tool Pi --apply
```

It writes `models`, `tools` and `display_name`, the same field names full matches use, and renames the replay to
`<display_name>.replay` with `meta.replay` following it. The display name mirrors the full-match shape:

```text
<case> <task> [track] · <YYYYMMDD HH-MM> · <model> - <tool> · s<seed>
CASE2-LTE 2_6_4 realtime · 20261110 15-56 · DeepSeek V4.1 Flash - Pi · s1331
```

`-` replaces the full-match `/` between model and tool so the same string is a valid Windows filename. `--run` can be
repeated to stamp a batch; without `--apply` it only prints the plan.

Then normalize the remaining artifacts to the full-match one-folder-per-match shape (per-run HTML in `eval/`, root
`replays/` twin removed when identical). A display-named replay is already the public identity, so this tool leaves it
and `meta.replay` untouched:

```powershell
python -B .\evaluate\tools\archive_micro_runs.py
python -B .\evaluate\tools\archive_micro_runs.py --apply
```

It is a dry run first, moves instead of copying, and reports conflicts instead of choosing a file.

Then run the case evaluator against the moved directory:

```powershell
python -B .\evaluate\micro\CASE1-duel\evaluate.py     .\evaluate\output\micro\CASE1-duel\<run-directory>     --dist .\desktop\build\headless
python -B .\evaluate\micro\CASE2-LTE\evaluate.py      .\evaluate\output\micro\CASE2-LTE\<run-directory>
python -B .\evaluate\micro\CASE3-Transport\evaluate.py .\evaluate\output\micro\CASE3-Transport\<run-directory>
python -B .\evaluate\micro\CASE4-Retreat\evaluate.py  .\evaluate\output\micro\CASE4-Retreat\<run-directory>
```

CASE1 additionally re-simulates the recording, so it needs `--dist`; CASE2/3/4 evaluate live engine evidence directly.

After all runs of a case are evaluated, only CASE1 currently has an aggregate report:

```powershell
python -B .\evaluate\micro\CASE1-duel\report_html.py
```

## Ownership boundary

| Location | Owner | Rule |
|---|---|---|
| `<run>\rwx.cmd`, `port`, `micro-run.json` | launcher | Agent invokes the wrapper only. |
| `<run>\tmp\` | assigned Agent | Its only writable location. |
| `<run>\logs`, `commands`, `events-live`, `replays`, `micro-output` | runtime | Agent must not inspect or mutate them. |
| `evaluate/output/micro/<case>/` | administrator | Receives completed evidence only through `collect_runs.py`. |

The normal full-match workflow is separate; see [PARALLEL_EVALUATION.md](PARALLEL_EVALUATION.md).
