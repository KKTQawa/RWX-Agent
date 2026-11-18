#Requires -Version 7
<#
.SYNOPSIS
Import one finished parallel-evaluation run into the evaluation batch and score it.

.DESCRIPTION
A finished run directory holds `commands/`, `events-live/` and `replays/` under the names the runtime
wrote. This script moves them into the canonical batch layout
`<out>/<map>-<yyyyMMdd>--<HH-mm>_<tool-slug>/`, keeps the rest as `source-run/`, then runs replay
parsing, preprocessing, Stage1/Stage3/v2/v2.1 scoring and writes `meta.json`.

It is a dry run by default: nothing is moved or written until `-Apply` is given.

After `-Apply` it prints the remaining batch commands (corpus re-run, v2.1 ledger, web rebuild, match
ids, site check) because those operate on the whole batch, not on one match.

.PARAMETER Run
Run directory created by `start-evaluation-run.ps1`, e.g. `X:\game\RWX-multiagent\run-003`.
Omit it to take the newest `run-*` under `X:\game\RWX-multiagent`.

.PARAMETER Tool
Harness that drove the match; it decides the directory slug and the `meta.json` tool label.
`Human` is the human baseline: no command log, Stage1 recorded as 0, Stage3 only.

.PARAMETER Batch
After scoring, also run the whole-batch steps (`--current`, `add_v21_scores`, `build_web_results_v2`,
`build_match_ids`, `check_site`). Required if this match must show up on the page.

.PARAMETER OutRoot
Where the match directory is created; defaults to `evaluate/output` (the public batch). Point it at a
scratch directory to score a match without touching the ledger.

.PARAMETER Apply
Actually move the materials and score the match. Without it only the plan is printed.

.PARAMETER KeepSource
Keep the (now empty of materials) run directory instead of deleting it.

.EXAMPLE
.\agent-operation\server\collect-evaluation-run.ps1 -Tool Human -Apply -Batch

.EXAMPLE
.\agent-operation\server\collect-evaluation-run.ps1 -Run X:\game\RWX-multiagent\run-003 -Tool Pi -Apply
#>
param(
    [string]$Run,
    [ValidateSet('Pi', 'CommandCode', 'DSH', 'Codex', 'Claude Code', 'OpenChamber', 'OpenCode v2', 'Human')]
    [string]$Tool = 'Pi',
    [string]$Model = 'deepseek-v4.1-flash',
    [string]$Provider = 'opencode',
    [string]$Thinking = 'high',
    [string]$DisplayStamp,
    [string]$OutRoot,
    [switch]$KeepSource,
    [switch]$Batch,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
$output = if ($OutRoot) { (Resolve-Path -LiteralPath $OutRoot).Path } else { Join-Path $repo 'evaluate\output' }

$slugs = @{
    'Pi' = 'pi'; 'CommandCode' = 'commandcode'; 'DSH' = 'dsh'; 'Codex' = 'codex'
    'Claude Code' = 'claude-code'; 'OpenChamber' = 'openchamber'; 'OpenCode v2' = 'opencodev2'
    'Human' = 'human'
}
$slug = $slugs[$Tool]

function First-Entry([string]$dir, [string]$kind) {
    if (-not (Test-Path -LiteralPath $dir)) { return $null }
    $items = Get-ChildItem -LiteralPath $dir -ErrorAction SilentlyContinue
    $items = if ($kind -eq 'file') { $items | Where-Object { -not $_.PSIsContainer } } else { $items | Where-Object { $_.PSIsContainer } }
    return $items | Select-Object -First 1
}

# 不带 -Run 时取最新的 run-*：一条命令就能收一局，不用记目录名。
if (-not $Run) {
    $latest = Get-ChildItem -LiteralPath 'X:\game\RWX-multiagent' -Directory -Filter 'run-*' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) { throw '没有 -Run，且 X:\game\RWX-multiagent 下找不到 run-* 目录；请加 -Run <目录>' }
    $Run = $latest.FullName
    Write-Host "run      : $Run（未指定 -Run，取最新的 run-*）"
}
if (-not (Test-Path -LiteralPath $Run)) { throw "run directory not found: $Run" }
$commands = First-Entry (Join-Path $Run 'commands') 'file'
$evidence = First-Entry (Join-Path $Run 'events-live') 'dir'
$replay = First-Entry (Join-Path $Run 'replays') 'file'
# 人类局没有可评的命令日志：`commands\` 里最多是开局用的 lobby 日志（rwx-ping / rwx-battleroom-*），
# 那是 CLI 客户端自己的记录，不是玩家的操作，不能拿去算 Stage1。整份丢进 source-run 留证即可。
if ($Tool -eq 'Human') { $commands = $null }
# 命令日志不是必需：人类局没有 CLI，Stage1 记 0（见 evaluate/preprocess.js）。
# 回放是硬要求：没有回放就无法复核，材料不全的对局一律不评（人类局尤其如此——人一旦漏了
# `play`/`--record`，那局就只剩 live 遥测，不能算数）。
foreach ($item in @($evidence, $replay)) {
    if (-not $item) {
        $what = if ($item -eq $replay) { 'replays/（本局没有录制；人类局请用 play <地图> 或 -Human -Map 开局）' }
            else { 'events-live/' }
        throw "run is missing $what : $Run"
    }
}

# 地图名与时间戳：地图取遥测 meta；时间戳优先命令日志名，其次证据目录名（match-001-<yyyyMMdd>-<HHmmss>-…），
# 都没有时退回回放的修改时间。
$telemetry = Get-ChildItem -LiteralPath $evidence.FullName -Recurse -Filter 'telemetry.jsonl' -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $telemetry) { throw "no telemetry.jsonl under $($evidence.FullName)" }
$head = Get-Content -LiteralPath $telemetry.FullName -TotalCount 1
$map = if ($head -match '"map":"([^"]*)"') { $matches[1] } else { $null }
if (-not $map) { throw "telemetry meta has no map name: $($telemetry.FullName)" }
if ($commands -and $commands.Name -match '-(\d{8})--(\d{2})-(\d{2})\.txt$') {
    $date, $hh, $mm = $matches[1], $matches[2], $matches[3]
} elseif ($evidence.Name -match '-(\d{8})-(\d{2})(\d{2})(\d{2})-') {
    # `match-001-20261115-224617-team0-…`：日期 + HHmmss。
    $date, $hh, $mm = $matches[1], $matches[2], $matches[3]
} else {
    $date, $hh, $mm = $replay.LastWriteTime.ToString('yyyyMMdd'), $replay.LastWriteTime.ToString('HH'), $replay.LastWriteTime.ToString('mm')
}
$stamp = "$date--$hh-$mm"

# `[2p]` -> `(2p)`，其余方括号去掉，空格转连字符：与既有目录（`Whale-(2p)-By-Tstis-…`）一致。
$mapSlug = $map -replace '\[(\d+p)\]', '($1)' -replace '[\[\]]', '' -replace '\s+', '-' `
    -replace '[<>:"/\\|?*]', ''
$match = "$mapSlug-$stamp`_$slug"
$target = Join-Path $output $match
if (Test-Path -LiteralPath $target) { throw "target already exists: $target" }

$sizeMb = [math]::Round(((Get-ChildItem -LiteralPath $evidence.FullName -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
Write-Host "run      : $Run"
Write-Host "match    : $match"
Write-Host "map      : $map"
Write-Host "tool     : $Tool (slug: $slug)"
Write-Host "evidence : $($evidence.Name) ($sizeMb MB)"
Write-Host "commands : $(if ($commands) { $commands.Name } else { '（无命令日志：人类局，Stage1 记 0）' })"
Write-Host "replay   : $($replay.Name)"
if (-not $Apply) {
    Write-Host ''
    Write-Host 'Dry run: nothing moved. Re-run with -Apply to import and score this match.'
    return
}

New-Item -ItemType Directory -Path $target -Force | Out-Null
if ($commands) { Move-Item -LiteralPath $commands.FullName -Destination (Join-Path $target "commands-$match.txt") }
New-Item -ItemType Directory -Path (Join-Path $target 'events-live') -Force | Out-Null
Move-Item -LiteralPath $evidence.FullName -Destination (Join-Path $target 'events-live' $match)
New-Item -ItemType Directory -Path (Join-Path $target 'replay') -Force | Out-Null
Move-Item -LiteralPath $replay.FullName -Destination (Join-Path $target 'replay' "$match.replay")

$sourceRun = Join-Path $target 'source-run'
New-Item -ItemType Directory -Path $sourceRun -Force | Out-Null
# 无命令日志（人类局）时 `commands\` 也是普通材料：里面的 lobby 日志要跟着进 source-run。
$keptInRun = @('events-live', 'replays')
if ($commands) { $keptInRun += 'commands' }
foreach ($entry in Get-ChildItem -LiteralPath $Run -Force) {
    if ($entry.Name -in $keptInRun) { continue }
    $destination = Join-Path $sourceRun $entry.Name
    if (Test-Path -LiteralPath $destination) { continue }
    Move-Item -LiteralPath $entry.FullName -Destination $destination
}
foreach ($name in @('commands', 'events-live', 'replays')) {
    $dir = Join-Path $Run $name
    if ((Test-Path -LiteralPath $dir) -and -not (Get-ChildItem -LiteralPath $dir -Force)) {
        Remove-Item -LiteralPath $dir -Force
    }
}
if (-not $KeepSource) {
    if (-not (Get-ChildItem -LiteralPath $Run -Force)) {
        # 可见客户端会留一个终端停在这个目录里，那时删不掉是正常的（材料已经搬完）。
        try { Remove-Item -LiteralPath $Run -Force -Recurse }
        catch { Write-Warning "run directory kept (still open in a terminal?): $Run" }
    }
    else { Write-Warning "run directory not empty, kept: $Run" }
}

$replayArgs = @((Join-Path $target "replay\$match.replay"))
if ($commands) { $replayArgs += @('--commands', (Join-Path $target "commands-$match.txt")) }
python evaluate/utils/replay.py @replayArgs
if ($LASTEXITCODE -ne 0) { throw 'replay parsing failed' }
# replay.py 总把解析产物写到 `evaluate/output/<match>/replay`；用 -OutRoot 时把它们搬回目标目录。
$batchMatch = Join-Path $repo "evaluate\output\$match"
if ((Resolve-Path -LiteralPath $target).Path -ne $batchMatch -and (Test-Path -LiteralPath $batchMatch)) {
    Get-ChildItem -LiteralPath (Join-Path $batchMatch 'replay') -File |
        Move-Item -Destination (Join-Path $target 'replay') -Force
    Remove-Item -LiteralPath $batchMatch -Recurse -Force
}

node evaluate/preprocess.js $target
if ($LASTEXITCODE -ne 0) { throw 'preprocessing failed' }
node evaluate/tools/evaluate_corpus_v2.js --match $target | Out-Host
if ($LASTEXITCODE -ne 0) { throw 'scoring failed' }
if (-not (Test-Path -LiteralPath (Join-Path $target 'evaluation_v2.json'))) {
    throw 'scoring produced no evaluation_v2.json — usually commands/economy.log/telemetry is missing (see the IGNORE line above)'
}

$evaluation = Get-Content -LiteralPath (Join-Path $target 'evaluation_v2.json') -Raw | ConvertFrom-Json
$outcome = $evaluation.result.outcome
$label = switch ($outcome) { 'win' { '胜利' } 'defeat' { '战败' } default { '未知' } }
$displayStamp = if ($DisplayStamp) { $DisplayStamp } else { "$($date.Substring(0,4))-$($date.Substring(4,2))-$($date.Substring(6,2)) $hh-$mm" }
# 人类局不写模型/工具链字段：网页靠 runner/tools.profile 把它归到「人类」行。
$overrides = @{ tool = $Tool; outcome = $outcome; resultLabel = $label }
if ($Tool -eq 'Human') {
    $overrides.display_name = "$map · $displayStamp · 人类"
    $overrides.note = "人类基线局：真人用鼠标打完，没有 CLI 命令日志；Stage1 按约定记 0，只评估 Stage3。材料来自 $Run。"
} else {
    $overrides.model = $Model; $overrides.provider = $Provider; $overrides.thinking = $Thinking
    $overrides.display_name = "$map · $displayStamp · DeepSeek V4.1 Flash / $Tool"
    $overrides.note = "由 $Tool 驱动（provider $Provider），材料来自 $Run。"
}

# 走 API 而不是 CLI：CLI 只认 evaluate/output，`-OutRoot` 时要指定别的根目录。
$payload = @{root = $output; match = $match; overrides = $overrides} | ConvertTo-Json -Depth 4 -Compress
node -e "const o=JSON.parse(process.argv[1]);const {consolidate}=require('./evaluate/tools/match_materials');const r=consolidate({root:o.root,replays:o.root,apply:true,match:o.match,overrides:o.overrides});console.log(r.matches.map(m=>m.match+': '+m.actions.length+' actions').join('\\n'))" $payload
if ($LASTEXITCODE -ne 0) { throw 'writing meta.json failed' }

Write-Host ''
Write-Host "scored: $match -> outcome=$outcome, total-v2.1=$($evaluation.scores.totalV21)"
Write-Host ''
if ($Batch) {
    $steps = @(
        @('node', 'evaluate/tools/evaluate_corpus_v2.js', '--current'),
        @('node', 'evaluate/tools/add_v21_scores.js', '--current-only'),
        @('node', 'evaluate/tools/build_web_results_v2.js'),
        @('python', 'web/tools/build_match_ids.py'),
        @('python', 'web/tools/check_site.py')
    )
    foreach ($step in $steps) {
        Write-Host ">> $($step -join ' ')"
        & $step[0] @($step[1..($step.Count - 1)])
        if ($LASTEXITCODE -ne 0) { throw "batch step failed: $($step -join ' ')" }
    }
    Write-Host ''
    Write-Host "done: $match 已进账本。"
} else {
    Write-Host 'Next (whole-batch steps; run from the repository root), or re-run this script with -Batch:'
    Write-Host '  node evaluate/tools/evaluate_corpus_v2.js --current'
    Write-Host '  node evaluate/tools/add_v21_scores.js --current-only'
    Write-Host '  node evaluate/tools/build_web_results_v2.js'
    Write-Host '  python web/tools/build_match_ids.py'
    Write-Host '  python web/tools/check_site.py'
}
Write-Host ''
Write-Host 'Optional: copy the replay into the repository archive:'
Write-Host "  Copy-Item -LiteralPath '$target\replay\$match.replay' 'replays\$match.replay'"
