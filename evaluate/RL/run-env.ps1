[CmdletBinding()]
param(
    # Environment file (JSON): map, room rules, seed, slot -> AI. See README.md.
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Env,

    # Override the environment's out directory (default: evaluate/RL/out/<env name>).
    [string]$Out,

    # Override limits.maxTicks (smoke runs).
    [int]$MaxTicks = 0,

    # Override the room seed without editing the file.
    [int]$Seed = 0,

    # Override the room income multiplier without editing the file.
    [double]$Income = 0,

    # Replay the recording back and report engine checksum mismatches.
    [switch]$Verify,

    # Print the materialized rollout spec instead of running.
    [switch]$DryRun,

    # Keep the run's stdout/stderr logs (always kept on disk).
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$envPath = (Resolve-Path -LiteralPath $Env).Path
$config = Get-Content -LiteralPath $envPath -Raw | ConvertFrom-Json
if ($config.schema -and $config.schema -ne 'rwx-rl-env-v1') {
    throw "Unsupported environment schema '$($config.schema)'; expected rwx-rl-env-v1"
}
if (-not $config.slots -or $config.slots.Count -lt 2) {
    throw "The environment needs at least two slots (one AI per side)"
}

# Knobs may be plain values or documented wrappers {"value":x,"original":y,"min":..,"max":..,"note":".."}.
$effective = [ordered]@{}

function Get-Knob {
    param([object]$Node, [string]$Path, $Fallback)
    if ($null -eq $Node) { return $Fallback }
    if ($Node -is [System.Management.Automation.PSCustomObject] -and $null -ne $Node.PSObject.Properties['value']) {
        $value = $Node.value
        if ($null -ne $Node.PSObject.Properties['min'] -and ($value -is [ValueType]) -and ($Node.min -is [ValueType]) -and [double]$value -lt [double]$Node.min) {
            throw "$Path = $value is below min $($Node.min)"
        }
        if ($null -ne $Node.PSObject.Properties['max'] -and ($value -is [ValueType]) -and ($Node.max -is [ValueType]) -and [double]$value -gt [double]$Node.max) {
            throw "$Path = $value is above max $($Node.max)"
        }
        $effective[$Path] = $value
        if ($Node.PSObject.Properties['original']) { $effective["$Path.original"] = $Node.original }
        if ($Node.PSObject.Properties['min']) { $effective["$Path.min"] = $Node.min }
        if ($Node.PSObject.Properties['max']) { $effective["$Path.max"] = $Node.max }
        return $value
    }
    $effective[$Path] = $Node
    return $Node
}

function Resolve-RlPath([string]$value) {
    if ([System.IO.Path]::IsPathRooted($value)) { return [System.IO.Path]::GetFullPath($value) }
    return [System.IO.Path]::GetFullPath((Join-Path $repo $value))
}

function Normalize-Name([string]$value) { ($value -replace '[^\p{L}\p{N}]', '').ToLowerInvariant() }

# --- map: .tmx path, or a name fragment matched against official (assets/maps) and custom (mods/maps) maps
function Get-DisplayName([string]$base) {
    # Mirrors MapMetadata.getMapName: drop a leading "l123;" and/or "[tag]" prefix, "_" -> " ", capitalize.
    $n = $base
    $n = [regex]::Replace($n, '^l\d*;', '')
    $n = [regex]::Replace($n, '^ *\[[^\]]*\]', '')
    if ($n.Length -ge 1) { $n = $n.Substring(0,1).ToUpperInvariant() + $n.Substring(1) }
    return ($n -replace '_', ' ')
}
function Get-NameCore([string]$text) {
    $n = ($text -replace '[^\p{L}\p{N}]', '').ToLowerInvariant()
    $n = [regex]::Replace($n, '^\d+p', '')
    $n = [regex]::Replace($n, '\d+p$', '')
    return $n
}

$mapValue = [string]$config.map
if ($mapValue -match '\.tmx$') {
    $mapPath = Resolve-RlPath $mapValue
    if (-not (Test-Path -LiteralPath $mapPath)) { throw "Map not found: $mapPath" }
} else {
    $sources = @(
        @{ Dir = (Join-Path $repo 'mods\maps'); Kind = '自定义' },
        @{ Dir = (Join-Path $repo 'assets\maps\skirmish'); Kind = '官方' },
        @{ Dir = (Join-Path $repo 'assets\maps\normal'); Kind = '官方战役' },
        @{ Dir = (Join-Path $repo 'assets\maps\challenge'); Kind = '官方挑战' },
        @{ Dir = (Join-Path $repo 'assets\maps\survival'); Kind = '官方生存' },
        @{ Dir = (Join-Path $repo 'assets\maps\testing'); Kind = '官方测试' }
    )
    $index = @()
    foreach ($source in $sources) {
        if (-not (Test-Path -LiteralPath $source.Dir)) { continue }
        foreach ($file in Get-ChildItem -LiteralPath $source.Dir -Filter '*.tmx' -File) {
            $display = Get-DisplayName $file.BaseName
            $index += [pscustomobject]@{
                Path = $file.FullName
                Kind = $source.Kind
                Name = $display
                Core = Get-NameCore $display
                BaseCore = Get-NameCore $file.BaseName
            }
        }
    }
    $wanted = Get-NameCore $mapValue
    if (-not $wanted) { throw "Map fragment '$mapValue' has no letters or digits" }
    $exact = @($index | Where-Object { $_.Core -eq $wanted -or $_.BaseCore -eq $wanted })
    $hits = if ($exact.Count -gt 0) { $exact } else { @($index | Where-Object { $_.Core.Contains($wanted) -or $_.BaseCore.Contains($wanted) }) }
    if ($hits.Count -eq 0) {
        $names = ($index | Sort-Object Kind, Name | ForEach-Object { "  [$($_.Kind)] $($_.Name)" }) -join "`n"
        throw "No map matches '$mapValue'. Candidates:`n$names"
    }
    if ($hits.Count -gt 1) {
        $names = ($hits | ForEach-Object { "  [$($_.Kind)] $($_.Name)" }) -join "`n"
        throw "'$mapValue' matches more than one map; use a longer fragment or a .tmx path:`n$names"
    }
    $mapPath = $hits[0].Path
    $script:mapKind = $hits[0].Kind
}
# --- output directory: default inside the repo so materials stay with the configs
$envName = if ($config.name) { [string]$config.name } else { [System.IO.Path]::GetFileNameWithoutExtension($envPath) }
$runPath = if ($Out) { [System.IO.Path]::GetFullPath($Out) }
           elseif ($config.out) { Resolve-RlPath ([string]$config.out) }
           else { Join-Path $repo "evaluate\RL\out\$envName" }
# A dry run must not litter evaluate/RL/out with empty directories.
if (-not $DryRun -or (Test-Path -LiteralPath $runPath)) { New-Item -ItemType Directory -Path $runPath -Force | Out-Null }

# --- primary AI config: all slots using the primary preset share this file
$aiConfigs = @($config.slots | Where-Object { $_.aiConfig } | ForEach-Object { Resolve-RlPath $_.aiConfig })
$aiConfig = $null
if ($aiConfigs.Count -gt 0) {
    $aiConfig = $aiConfigs[0]
    if ($aiConfigs.Count -gt 1) {
        $distinct = $aiConfigs | Select-Object -Unique
        if ($distinct.Count -gt 1) {
            throw "Several slots use different aiConfig files; use one file and its 'slots' section instead: $($distinct -join ', ')"
        }
    }
    if (-not (Test-Path -LiteralPath $aiConfig)) { throw "AI config not found: $aiConfig" }
}

# --- room + seed + limits + sampling, each knob unwrapped and range-checked
$room = [ordered]@{}
$roomSource = $config.room
foreach ($property in @('incomeMultiplier', 'startingCredits', 'fogMode', 'revealedMap', 'startingUnits', 'noNukes', 'aiDifficulty')) {
    $node = if ($roomSource) { $roomSource.$property } else { $null }
    $value = Get-Knob $node "room.$property" $null
    if ($null -ne $value) { $room[$property] = $value }
}

# seed: top-level wins over room.seed (top-level is the documented, more visible place)
$seedNode = if ($null -ne $config.seed) { $config.seed } else { $roomSource.seed }
$seedValue = Get-Knob $seedNode 'seed' 0
if ($Seed -ne 0) { $seedValue = $Seed; $effective['seed'] = $Seed }
$room['seed'] = [int]$seedValue
if ($Income -gt 0) { $room['incomeMultiplier'] = $Income; $effective['room.incomeMultiplier'] = $Income }

$limits = [ordered]@{}
if ($config.limits) {
    foreach ($property in @('maxTicks', 'maxWallSeconds')) {
        $value = Get-Knob $config.limits.$property "limits.$property" $null
        if ($null -ne $value) { $limits[$property] = $value }
    }
}
if ($MaxTicks -gt 0) { $limits['maxTicks'] = $MaxTicks; $effective['limits.maxTicks'] = $MaxTicks }

$sampling = [ordered]@{}
if ($config.sampling) {
    foreach ($property in @('everyTicks', 'includeUnitTypes')) {
        $value = Get-Knob $config.sampling.$property "sampling.$property" $null
        if ($null -ne $value) { $sampling[$property] = $value }
    }
}

$spec = [ordered]@{
    schema = 'rwx-rollout-v1'
    map = $mapPath
    out = $runPath
    record = if ($null -ne $config.record) { [bool]$config.record } else { $true }
    winCondition = if ($config.winCondition) { [string]$config.winCondition } else { 'commandCenter' }
    room = $room
    teams = @($config.slots | Sort-Object { [int]$_.slot } | ForEach-Object {
        $team = [ordered]@{ slot = [int]$_.slot; ai = [string]$_.ai }
        if ($_.name) { $team.name = [string]$_.name }
        if ($null -ne $_.spawn) { $team.spawn = [int]$_.spawn }
        if ($null -ne $_.side) { $team.side = [int]$_.side }
        $team
    })
    limits = $limits
    # An environment without a sampling block produces no samples.jsonl at all.
    sampling = if ($config.sampling) { $sampling } else { $false }
}
if ($config.perspective) { $spec.perspective = $config.perspective }
if ($aiConfig) { $spec.aiConfig = $aiConfig }
if ($config.aiConfig2) {
    $aiConfig2 = Resolve-RlPath $config.aiConfig2
    if (-not (Test-Path -LiteralPath $aiConfig2 -PathType Leaf)) { throw "Second AI config not found: $aiConfig2" }
    $spec.aiConfig2 = $aiConfig2
}
# Optional per-frame telemetry (evaluate-side EngineEvidence): telemetry.jsonl + economy.log.
if ($null -ne $config.telemetry) { $spec.telemetry = [bool](Get-Knob $config.telemetry 'telemetry' $false) }

$specPath = Join-Path $runPath 'env-resolved.json'
if (-not $DryRun -or (Test-Path -LiteralPath $runPath)) {
    [System.IO.File]::WriteAllText($specPath, ($spec | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))
}
if (-not $Quiet) {
    Write-Host "Environment : $envName  ($envPath)"
    Write-Host "Map         : $mapPath"
    Write-Host ("Slots       : " + (@($spec.teams | ForEach-Object { "#$($_.slot)=$($_.ai)" }) -join ', '))
    Write-Host ("Room        : income=$($room.incomeMultiplier) seed=$($room.seed) fog=$($room.fogMode) revealed=$($room.revealedMap) credits=$($room.startingCredits)")
    Write-Host ("Limits      : maxTicks=$($limits.maxTicks) maxWallSeconds=$($limits.maxWallSeconds) samplingEvery=$($sampling.everyTicks)")
    if ($aiConfig) { Write-Host "AI config   : $aiConfig" }
    if ($spec.aiConfig2) { Write-Host "Second AI   : $($spec.aiConfig2)" }
    Write-Host "Output      : $runPath"; if (-not $MaxTicks) { Write-Host "Mode        : 完整对局（跑到分出胜负；limits 只是防挂死上限）" } else { Write-Host "Mode        : 截断调试（-MaxTicks $MaxTicks，不计为完整对局）" }
    if (Test-Path -LiteralPath $specPath) { Write-Host "  resolved  : $specPath" } else { Write-Host "  resolved  : (dry run, not written)" }
}
if ($DryRun) { return }

& (Join-Path $PSScriptRoot '..\..\agent-operation\tools_developer\start-rollout.ps1') `
    -Spec $specPath -Out $runPath -Verify:$Verify -Quiet:$Quiet

if (-not $Quiet) {
    $resultPath = Join-Path $runPath 'result.json'
    if (Test-Path -LiteralPath $resultPath) {
        $result = Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
        $replayDir = Join-Path $runPath 'replays'
        $replays = if (Test-Path -LiteralPath $replayDir) { @(Get-ChildItem -LiteralPath $replayDir -Filter '*.replay') } else { @() }
        Write-Host ""
        Write-Host "产物（这一局的全部材料都在这一个目录里）:"
        Write-Host "  $runPath\"
        Write-Host "    result.json      结算 + 生效值 + 队伍态（outcome=$($result.outcome) ticks=$($result.ticks)）"
        Write-Host "    samples.jsonl    按 tick 采样（每 $($sampling.everyTicks) tick 一行）"
        if ($replays.Count -gt 0) { Write-Host "    replays\         回放：$($replays.Name -join ', ')" }
        if (Test-Path -LiteralPath (Join-Path $runPath 'replays')) {
            $checks = @(Get-ChildItem -LiteralPath (Join-Path $runPath 'replays') -Filter '*.check.json' -ErrorAction SilentlyContinue)
            if ($checks.Count -gt 0) { Write-Host "                     回放校验：$($checks.Name -join ', ')" }
        }
        Write-Host "    env-resolved.json  本次实际生效的 spec（含 seed/收入等解析后的值）"
        Write-Host "    spec.json        启动器写回的有效 spec"
        Write-Host "    rollout.log      引擎 stdout（rollout.err.log 为 stderr）"
    }
}
