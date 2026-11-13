# Parallel evaluation runs

For the separate automatic-recording micro-evaluation workflow, use [PARALLEL_MICRO_EVALUATION.md](PARALLEL_MICRO_EVALUATION.md); this document is for full matches.

Each measured match has one directory outside the checkout. The directory is the match boundary: its port, player preferences, replay, command log, engine evidence and Agent scratch files never overlap another match.

## Start one run

Build the runtime once after code changes, then create a new run directory. Do not reuse an existing run directory.

```powershell
Set-Location X:\game\RWX
.\gradlew.bat :desktop:headlessDist
.\agent-operation\server\start-evaluation-run.ps1 -Run X:\game\RWX-multiagent\run-001
```

The command waits for `rwx-ping`, then prints the exact sentence to give the Agent. Start a separate process for every additional run; each call requires a distinct, initially absent directory.

For a visible game client, use `-Window`. The per-run isolation is unchanged.

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
