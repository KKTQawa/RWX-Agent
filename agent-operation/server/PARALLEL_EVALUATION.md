# Parallel evaluation runs

For the separate automatic-recording micro-evaluation workflow, use [PARALLEL_MICRO_EVALUATION.md](PARALLEL_MICRO_EVALUATION.md); this document is for full matches.

Each measured match has one directory outside the checkout. The directory is the match boundary: its port, player preferences, replay, command log, engine evidence and Agent scratch files never overlap another match.

## Start one run

Build the runtime once after code changes, then create a new run directory. Do not reuse an existing run directory.

```powershell
Set-Location X:\game\RWX
.\gradlew.bat :desktop:headlessDist
.\agent-operation\server\start-evaluation-run.ps1 -Run X:\game\RWX-multiagent\run-008 `
    -Headless:$true -CommandCenterWinCondition:$true
```

Both switches default to `$true`, so the two arguments above are explicit documentation rather than a requirement. `-Headless:$false` (or the older `-Window`) opens a visible client; `-CommandCenterWinCondition:$false` restores the map's own victory condition (stock skirmish: a team loses when it has no builder or mobile unit left). The launcher appends `--headless` and/or `--win-condition=commandCenter` to the game arguments.

The command waits for `rwx-ping`, then prints the exact sentence to give the Agent. Start a separate process for every additional run; each call requires a distinct, initially absent directory. The printed object also reports the effective `Headless` and `WinCondition` values.

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

The repository's `agent-operation/tmp`, `agent-tmp`, `replays`, and `evaluate/output` are legacy single-instance locations. They are neither inputs nor outputs of a parallel evaluation run.

## Evidence and recovery

The launcher passes an explicit port, evidence directory, command-capture directory and log directory to the game. Replays remain under `<run>\replays` because the process working directory and `--data-dir` are both `<run>`.

If readiness times out, retain the run unchanged and inspect `logs\game.stdout.log` and `logs\game.stderr.log`. Do not point an Agent at another run or substitute a repository-level port file.
