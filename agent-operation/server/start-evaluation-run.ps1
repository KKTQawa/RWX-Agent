[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Run,

    [ValidateRange(1, 3)]
    [int]$Tier = 2,

    [switch]$Window,

    # Default: no window, no graphics, no audio. `-Headless:$false` (or the older `-Window`)
    # starts a visible client instead; both the isolation and the launch arguments are otherwise
    # identical, so a visible client is only a different render backend.
    [bool]$Headless = $true,

    # Evaluation rule: a team loses as soon as every command center it owns is destroyed, and the
    # match ends there. `$false` keeps the map's own win condition (stock skirmish: no builder or
    # mobile unit left). Every client in a networked match must use the same value.
    [bool]$CommandCenterWinCondition = $true,

    # Human baseline: a visible client that goes straight into a recorded skirmish, so a person can
    # play with the mouse and still produce evaluation materials (`Stage1` is not scored for humans).
    # Implies `-Headless:$false`. Give `-Map` to start the match; without it the run only opens the
    # lobby and lists the maps found under `-MapsFrom`.
    [switch]$Human,

    # Map to start, by display name, file name or resource path (`[2]方岛战争`, `Whale_[2p]_[By Tstis]`).
    [string]$Map,

    # AI opponent added to the first free slot for `-Human`.
    [ValidateSet('very-easy', 'easy', 'medium', 'hard', 'very-hard', 'impossible')]
    [string]$Difficulty = 'medium',

    # Where `-Human` takes the map from; the chosen `.tmx` (and its preview) is copied into the run.
    [string]$MapsFrom,

    # List the maps found under `-MapsFrom` and exit.
    [switch]$ListMaps,

    # A visible client also opens a client terminal (`<run>\rwx-shell.ps1`) where `rwx …` works;
    # closing that window does not touch the game or the evaluation materials. Suppress it here.
    [switch]$NoTerminal,

    # 脚本 AI 基线：把“本地玩家”那一队改成 AI，对手也由 AI 占位，全程无人操作。
    # 取值同 `--difficulty`：原版档位、自定义 AI 的 id 或显示名（例如 'rwx.ai-rl-hard'）。
    [string]$PlayerAi,

    # 对手 AI（脚本 AI 模式下生效），默认 medium，和 54 局现有对局的对照条件一致。
    [string]$OpponentAi = 'medium',

    # 玩家 AI 的配置文档（-Drwx.rl.aiConfig）；不给就用预设默认值。
    [string]$AiConfig,

    # 覆盖玩家 AI 的内置经济倍率加成（写死 1.0）：让脚本 AI 和人类/agent 的 1.0 收入对齐。
    # 不加这个开关就保持内置加成（RL Hard-up=1.4、Very Hard=1.8 …）。
    [switch]$NormalizeAiIncome,

    # 时间标定：realtime（可上榜，默认）| fast:8（加速彩排，证据里记 diagnostic 且不可上榜）。
    [string]$Speed = 'realtime',

    # 采集哪一队。脚本 AI 模式下本地玩家已转旁观，必须显式指定玩家 AI 的队号
    # （第一个加的 AI 落在出生点 1，队号 0）。-1 = 不设置，沿用引擎默认（本地玩家队）。
    [int]$EvaluateTeam = -1
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ($Human) { $Headless = $false }
if (-not $MapsFrom) { $MapsFrom = Join-Path $repo 'mods' }

# 地图只在 `<run>\mods\maps` 里才会出现在游戏的列表里，所以开局前先解析出要用的那一份。
function Normalize-MapName([string]$value) { ($value -replace '[^\p{L}\p{N}]', '').ToLowerInvariant() }
$mapsDir = Join-Path $MapsFrom 'maps'
$mapCandidates = if (Test-Path -LiteralPath $mapsDir) {
    @(Get-ChildItem -LiteralPath $mapsDir -Filter '*.tmx' -File | Sort-Object BaseName)
} else { @() }
if ($ListMaps) {
    if (-not $mapCandidates.Count) { throw "找不到地图目录：$mapsDir（用 -MapsFrom 指定含 maps\ 的目录）" }
    $mapCandidates | ForEach-Object { $_.BaseName }
    return
}
if ($Human -and -not $Map) {
    throw "-Human 需要 -Map <地图名>（先跑一次 -ListMaps 看可选地图）。"
}
$mapFile = $null
if ($Map) {
    if (-not $mapCandidates.Count) { throw "找不到地图目录：$mapsDir（用 -MapsFrom 指定含 maps\ 的目录）" }
    $wanted = ($Map -replace '\.tmx$', '')
    $mapFile = $mapCandidates | Where-Object { $_.BaseName -eq $wanted } | Select-Object -First 1
    if (-not $mapFile) { $mapFile = $mapCandidates | Where-Object { $_.BaseName -ieq $wanted } | Select-Object -First 1 }
    if (-not $mapFile) {
        $target = Normalize-MapName $wanted
        $mapFile = $mapCandidates | Where-Object { (Normalize-MapName $_.BaseName) -eq $target } | Select-Object -First 1
        if (-not $mapFile) {
            $mapFile = $mapCandidates | Where-Object { (Normalize-MapName $_.BaseName).Contains($target) } | Select-Object -First 1
        }
    }
    if (-not $mapFile) {
        $names = ($mapCandidates | ForEach-Object { '  ' + $_.BaseName }) -join "`n"
        throw "找不到地图：$Map。$mapsDir 下可选：`n$names"
    }
}
$runPath = [System.IO.Path]::GetFullPath($Run)
$repoPrefix = $repo.TrimEnd('\') + '\'
if ($runPath.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Run must be outside the repository so it cannot share runtime files: $runPath"
}
if (Test-Path -LiteralPath $runPath) {
    throw "Run directory already exists; choose a new run id instead of reusing it: $runPath"
}

$distDir = Join-Path $repo 'desktop\build\headless'
if (-not (Test-Path -LiteralPath (Join-Path $distDir 'lib'))) {
    throw "Missing runtime distribution: $distDir. Build it first with .\gradlew.bat :desktop:headlessDist"
}
if ($null -eq (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'python is required by <run>\rwx.cmd but was not found on PATH.'
}

New-Item -ItemType Directory -Path $runPath | Out-Null
@('tmp', 'replays', 'commands', 'events-live', 'logs') |
    ForEach-Object { New-Item -ItemType Directory -Path (Join-Path $runPath $_) | Out-Null }
# A visible evaluation client has its own isolated settings root. Persist windowed mode explicitly
# instead of inheriting the engine's platform default, so each new run opens as a movable window.
@'
[preferences]
slick2dFullScreen = "false"
'@ | Set-Content -LiteralPath (Join-Path $runPath 'preferences.toml') -Encoding utf8
# 只搬这一张图（含 `_map.png` 预览）：整包 25 MB 会让每局材料多背一份用不到的地图。
if ($mapFile) {
    $runMaps = Join-Path $runPath 'mods\maps'
    New-Item -ItemType Directory -Path $runMaps -Force | Out-Null
    Copy-Item -LiteralPath $mapFile.FullName -Destination $runMaps
    $preview = Join-Path $mapFile.DirectoryName ($mapFile.BaseName + '_map.png')
    if (Test-Path -LiteralPath $preview) { Copy-Item -LiteralPath $preview -Destination $runMaps }
}

$portFile = Join-Path $runPath 'port'
$cmdPath = Join-Path $runPath 'rwx.cmd'
$cliPath = Join-Path $repo 'agent-operation\tools\rwx-cli.py'
@"
@echo off
python "$cliPath" --port-file "%~dp0port" --timeout 60 %*
"@ | Set-Content -LiteralPath $cmdPath -Encoding ascii

$java = Get-Command java -ErrorAction Stop
# JVM options must all sit before the main class: anything after it is parsed by `AppOptions`, which
# rejects unknown arguments (`Unsupported app argument: -Drwx.windowTitle=…`).
$jvmOptions = @(
    '-Xms256m', '-Xmx1536m', '-Dfile.encoding=UTF-8',
    '-Dorg.lwjgl.opengl.contextAPI=native', '-Dorg.lwjgl.system.stackSize=512',
    '--enable-native-access=ALL-UNNAMED', '--sun-misc-unsafe-memory-access=allow',
    "-Dlaunch.dir=$runPath", "-Drwx.repoDir=$repo", "-Drwx.log.dir=$(Join-Path $runPath 'logs')",
    "-Drwx.evaluate.dir=$(Join-Path $runPath 'events-live')",
    "-Drwx.cli.recordingDir=$(Join-Path $runPath 'commands')", '-Drwx.cli.terminal=false',
    "-Drwx.assetsDir=$(Join-Path $repo 'assets')"
)
if ($AiConfig) {
    $jvmOptions += "-Drwx.rl.aiConfig=$([System.IO.Path]::GetFullPath($AiConfig))"
}
if ($NormalizeAiIncome) {
    $jvmOptions += '-Drwx.ai.incomeMultiplier=1.0'
}
if ($EvaluateTeam -ge 0) {
    $jvmOptions += "-Drwx.evaluate.team=$EvaluateTeam"
}
# Visible clients all default to the same window title; stamp the run id so two windows can be told
# apart at a glance. Space-free on purpose: Start-Process does not quote arguments for us.
if ($Window -or -not $Headless) {
    $jvmOptions += "-Drwx.windowTitle=RWX-$([System.IO.Path]::GetFileName($runPath))"
}
$javaArguments = @($jvmOptions) + @(
    '-cp', (Join-Path $distDir 'lib\*'),
    'io.github.rwx.DesktopMain', '--no-steam', "--evaluate=$Tier", "--data-dir=$runPath",
    "--cli-port-file=$portFile"
)
if ($Headless -and -not $Window) { $javaArguments += '--headless' }
if ($CommandCenterWinCondition) { $javaArguments += '--win-condition=commandCenter' }
if ($Speed -and $Speed -ne 'realtime') { $javaArguments += "--speed-profile=$Speed" }

$stdout = Join-Path $runPath 'logs\game.stdout.log'
$stderr = Join-Path $runPath 'logs\game.stderr.log'
$process = Start-Process -FilePath $java.Source -ArgumentList $javaArguments -WorkingDirectory $runPath `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru

$ready = $false
$deadline = [DateTime]::UtcNow.AddSeconds(60)
while ([DateTime]::UtcNow -lt $deadline -and -not $process.HasExited) {
    if (Test-Path -LiteralPath $portFile) {
        & $cmdPath rwx-ping | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    }
    Start-Sleep -Milliseconds 250
}
if (-not $ready) {
    throw "RWX did not become ready within 60 seconds. Inspect $stdout and $stderr; process id=$($process.Id)."
}

# 可见客户端配一个 CLI 终端：里面 `rwx <命令>` 直接可用，选图/加 AI/开录像都在那儿点。
# 那只是一个客户端进程——关掉窗口不影响游戏与材料，`collect-evaluation-run.ps1` 照常收。
if ((-not $Headless -or $Window) -and -not $NoTerminal) {
    $shellPath = Join-Path $runPath 'rwx-shell.ps1'
    $shellTemplate = @'
Set-Location -LiteralPath '__RUN__'
function rwx {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$cliArgs)
    & '__CMD__' @cliArgs
}
function play {
    param(
        [Parameter(Mandatory = $true)][string]$Map,
        [ValidateSet('very-easy', 'easy', 'medium', 'hard', 'very-hard', 'impossible')][string]$Difficulty = 'medium'
    )
    # --name 只认显示名或带 .tmx 的文件名：这里把 run 的 mods\maps 里的文件补齐扩展名。
    $candidate = $Map
    $mapsDir = Join-Path (Get-Location) 'mods\maps'
    if ($candidate -notmatch '\.tmx$' -and (Test-Path -LiteralPath $mapsDir)) {
        $hit = Get-ChildItem -LiteralPath $mapsDir -Filter '*.tmx' |
            Where-Object { $_.BaseName -ieq $candidate -or $_.BaseName -like "*$candidate*" } |
            Select-Object -First 1
        if ($hit) { $candidate = $hit.Name }
    }
    rwx rwx-skirmish
    rwx rwx-battleroom-select-map --name $candidate
    rwx rwx-battleroom-add-ai --difficulty $Difficulty
    rwx rwx-battleroom-start --record
    rwx rwx-game-replay-status
}
Write-Host ''
Write-Host 'RWX 客户端终端（run: __NAME__）' -ForegroundColor Cyan
Write-Host '  play ''Whale_[2p]_[By Tstis]''        选图 + 加 AI(medium) + 从 tick 0 录制，然后用鼠标打'
Write-Host '  play ''[2]方岛战争'' -Difficulty hard  指定对手难度'
Write-Host '  rwx rwx-battleroom-show --enabledMap   看这局能用哪些地图（官方地图一直都有）'
Write-Host '  rwx rwx-battleroom-show --currentMap   任何 rwx 命令都能直接敲'
Write-Host '  rwx rwx-game-replay-status             查看录像状态'
Write-Host ''
Write-Host '关掉这个窗口不影响评测；打完回来跑 collect-evaluation-run.ps1 -Tool Human -Apply -Batch。' -ForegroundColor DarkGray
Write-Host ''
'@
    $shellTemplate.Replace('__RUN__', $runPath).Replace('__CMD__', $cmdPath).
        Replace('__NAME__', [System.IO.Path]::GetFileName($runPath)) |
        Set-Content -LiteralPath $shellPath -Encoding utf8
    $shellExe = (Get-Command pwsh -ErrorAction SilentlyContinue)?.Source
    if (-not $shellExe) { $shellExe = (Get-Command powershell -ErrorAction Stop).Source }
    Start-Process -FilePath $shellExe -WorkingDirectory $runPath `
        -ArgumentList @('-NoLogo', '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', "`"$shellPath`"") | Out-Null
    Write-Host "CLI 终端已打开：$shellPath（关掉它不影响游戏与材料）"
}

# 端口通了不等于界面就绪（`rwx-ping` 在 UI 初始化前就能过），第一条命令要允许重试；
# 后面的命令都是一次性的，避免重复开局。
function Send-Rwx([string[]]$Arguments, [switch]$Retry) {
    $attempts = if ($Retry) { 10 } else { 1 }
    for ($attempt = 1; $attempt -le $attempts; $attempt++) {
        Write-Host ('> rwx ' + ($Arguments -join ' '))
        & python $cliPath --port-file $portFile --timeout 180 @Arguments
        if ($LASTEXITCODE -eq 0) { return }
        if ($attempt -lt $attempts) {
            Write-Host "  （界面还没就绪，2 秒后重试 $attempt/$attempts）"
            Start-Sleep -Seconds 2
        }
    }
    throw "rwx-cli 执行失败：$($Arguments -join ' ')"
}

# 人类对局：走和 Agent 一样的 CLI 开局路径（本地战役室 → 选图 → 加 AI → 从 tick 0 录制），
# 之后人就在窗口里用鼠标打；录像与证据由引擎自己写进 `<run>\replays`、`events-live`。
if ($Human) {
    Send-Rwx -Arguments @('rwx-skirmish') -Retry
    # `--name` 只认显示名或带 `.tmx` 的文件名，裸的 base name 会报 "Map is not enabled"。
    Send-Rwx -Arguments @('rwx-battleroom-select-map', '--name', $mapFile.Name)
    Send-Rwx -Arguments @('rwx-battleroom-add-ai', '--difficulty', $Difficulty)
    Send-Rwx -Arguments @('rwx-battleroom-start', '--record')
    Send-Rwx -Arguments @('rwx-game-replay-status')
    Write-Host ''
    Write-Host "人类对局已开始：$($mapFile.BaseName) vs AI $Difficulty，录像从 tick 0 写入 $runPath\replays。"
    Write-Host "打完回到终端：.\agent-operation\server\collect-evaluation-run.ps1 -Run $runPath -Tool Human -Apply -Batch"
    Write-Host '(也可以先 rwx-exit 再收；只要材料齐全即可)'
    Write-Host ''
}

# 脚本 AI 基线：本地玩家转旁观，两张座位都由 AI 占据 —— 没有人类/agent 操作，没有命令日志。
function Send-RwxSoft([string[]]$Arguments) {
    Write-Host ('> rwx ' + ($Arguments -join ' '))
    & python $cliPath --port-file $portFile --timeout 60 @Arguments 2>&1 | Out-Null
}
if ($PlayerAi) {
    if (-not $mapFile) { throw '-PlayerAi 需要 -Map <地图名>（先跑一次 -ListMaps 看可选地图）。' }
    Send-Rwx -Arguments @('rwx-skirmish') -Retry
    # 先把可选 AI 列表打出来：脚本 AI 是否已注册、能不能直接选中，日志里能直接看到。
    Send-Rwx -Arguments @('rwx-battleroom-show-ai')
    Send-Rwx -Arguments @('rwx-battleroom-select-map', '--name', $mapFile.Name)
    # 默认房间会带若干 AI，清掉它们（按出生点逐个移除，没有的直接忽略）。
    for ($spawn = 2; $spawn -le 10; $spawn++) {
        Send-RwxSoft -Arguments @('rwx-battleroom-set-player', '--player', "$spawn", '--kick')
    }
    # 本地玩家转旁观，把出生点 1 空出来给被测 AI。
    Send-Rwx -Arguments @('rwx-battleroom-set-player', '--player', '1', '--switch', 'spec')
    Send-Rwx -Arguments @('rwx-battleroom-add-ai', '--difficulty', $PlayerAi)
    Send-Rwx -Arguments @('rwx-battleroom-add-ai', '--difficulty', $OpponentAi)
    Send-Rwx -Arguments @('rwx-battleroom-show', '--player')
    Send-Rwx -Arguments @('rwx-battleroom-start', '--record')
    Write-Host ''
    Write-Host "脚本 AI 对局已开始：$($mapFile.BaseName) · 玩家位 $PlayerAi vs 对手 $OpponentAi（speed=$Speed, evaluateTeam=$EvaluateTeam）"
    Write-Host "打完：.\agent-operation\server\collect-evaluation-run.ps1 -Run $runPath -Tool ScriptAI -Apply"
    Write-Host ''
}

[PSCustomObject]@{
    Run = $runPath
    ProcessId = $process.Id
    Headless = ($Headless -and -not $Window)
    WinCondition = if ($CommandCenterWinCondition) { 'commandCenter' } else { 'map' }
    Human = [bool]$Human
    Map = if ($mapFile) { $mapFile.BaseName } else { $null }
    AgentPrompt = "Read $repo\agent-operation\START.md, then use $cmdPath for every game command."
    AgentWritableDirectory = Join-Path $runPath 'tmp'
    ReplayDirectory = Join-Path $runPath 'replays'
}
