[CmdletBinding()]
param(
    # Environment file (JSON): map, room rules, slot -> AI. See README.md.
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Env,

    # Override the environment's out directory.
    [string]$Out,

    # Override limits.maxTicks (smoke runs).
    [int]$MaxTicks = 0,

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
$schema = $config.schema
if ($schema -and $schema -ne 'rwx-rl-env-v1') {
    throw "Unsupported environment schema '$schema'; expected rwx-rl-env-v1"
}
if (-not $config.slots -or $config.slots.Count -lt 2) {
    throw "The environment needs at least two slots (one AI per side)"
}

function Resolve-RlPath([string]$value) {
    if ([System.IO.Path]::IsPathRooted($value)) { return [System.IO.Path]::GetFullPath($value) }
    return [System.IO.Path]::GetFullPath((Join-Path $repo $value))
}

function Normalize-Name([string]$value) { ($value -replace '[^\p{L}\p{N}]', '').ToLowerInvariant() }

# Map: either a .tmx path or a unique fragment of a map name under mods/maps.
$mapValue = [string]$config.map
$mapsDir = Join-Path $repo 'mods\maps'
if ($mapValue -match '\.tmx$') {
    $mapPath = Resolve-RlPath $mapValue
    if (-not (Test-Path -LiteralPath $mapPath)) { throw "Map not found: $mapPath" }
} else {
    if (-not (Test-Path -LiteralPath $mapsDir)) { throw "Map directory not found: $mapsDir" }
    $candidates = @(Get-ChildItem -LiteralPath $mapsDir -Filter '*.tmx' -File | Sort-Object BaseName)
    $wanted = Normalize-Name $mapValue
    $hits = @($candidates | Where-Object { (Normalize-Name $_.BaseName).Contains($wanted) })
    if ($hits.Count -eq 0) {
        $names = ($candidates | ForEach-Object { '  ' + $_.BaseName }) -join "`n"
        throw "No map matches '$mapValue' under $mapsDir. Candidates:`n$names"
    }
    if ($hits.Count -gt 1) {
        $names = ($hits | ForEach-Object { '  ' + $_.BaseName }) -join "`n"
        throw "'$mapValue' matches more than one map; use a longer fragment or a .tmx path:`n$names"
    }
    $mapPath = $hits[0].FullName
}

$runPath = if ($Out) { [System.IO.Path]::GetFullPath($Out) } else { [System.IO.Path]::GetFullPath([string]$config.out) }
if (-not $runPath) { throw "The environment needs an 'out' directory, or pass -Out" }
New-Item -ItemType Directory -Path $runPath -Force | Out-Null

# One AI config file per process: the configurable AI reads its preset once at startup. Different
# presets for different slots are expressed inside that file's "slots" section.
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

$room = [ordered]@{}
if ($config.room) {
    foreach ($property in $config.room.PSObject.Properties) { $room[$property.Name] = $property.Value }
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
        $team
    })
    limits = [ordered]@{}
    sampling = [ordered]@{}
}
if ($config.limits) { foreach ($p in $config.limits.PSObject.Properties) { $spec.limits[$p.Name] = $p.Value } }
if ($config.sampling) { foreach ($p in $config.sampling.PSObject.Properties) { $spec.sampling[$p.Name] = $p.Value } }
if ($MaxTicks -gt 0) { $spec.limits.maxTicks = $MaxTicks }
if ($aiConfig) { $spec.aiConfig = $aiConfig }

$specPath = Join-Path $runPath 'env-resolved.json'
[System.IO.File]::WriteAllText($specPath, ($spec | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))
if (-not $Quiet) {
    Write-Host "Environment : $($config.name)  ($envPath)"
    Write-Host "Map         : $mapPath"
    Write-Host ("Slots       : " + (@($spec.teams | ForEach-Object { "#$($_.slot)=$($_.ai)" }) -join ', '))
    Write-Host "Room        : income=$($room.incomeMultiplier) fog=$($room.fogMode) revealed=$($room.revealedMap) credits=$($room.startingCredits) seed=$($room.seed)"
    if ($aiConfig) { Write-Host "AI config   : $aiConfig" }
    Write-Host "Resolved    : $specPath"
}
if ($DryRun) { return }

& (Join-Path $PSScriptRoot '..\..\agent-operation\tools_developer\start-rollout.ps1') `
    -Spec $specPath -Out $runPath -Verify:$Verify -Quiet:$Quiet
