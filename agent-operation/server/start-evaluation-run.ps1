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
    [bool]$CommandCenterWinCondition = $true
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
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

$portFile = Join-Path $runPath 'port'
$cmdPath = Join-Path $runPath 'rwx.cmd'
$cliPath = Join-Path $repo 'agent-operation\tools\rwx-cli.py'
@"
@echo off
python "$cliPath" --port-file "%~dp0port" --timeout 60 %*
"@ | Set-Content -LiteralPath $cmdPath -Encoding ascii

$java = Get-Command java -ErrorAction Stop
$javaArguments = @(
    '-Xms256m', '-Xmx1536m', '-Dfile.encoding=UTF-8',
    '-Dorg.lwjgl.opengl.contextAPI=native', '-Dorg.lwjgl.system.stackSize=512',
    '--enable-native-access=ALL-UNNAMED', '--sun-misc-unsafe-memory-access=allow',
    "-Dlaunch.dir=$runPath", "-Drwx.repoDir=$repo", "-Drwx.log.dir=$(Join-Path $runPath 'logs')",
    "-Drwx.evaluate.dir=$(Join-Path $runPath 'events-live')",
    "-Drwx.cli.recordingDir=$(Join-Path $runPath 'commands')", '-Drwx.cli.terminal=false',
    "-Drwx.assetsDir=$(Join-Path $repo 'assets')", '-cp', (Join-Path $distDir 'lib\*'),
    'io.github.rwx.DesktopMain', '--no-steam', "--evaluate=$Tier", "--data-dir=$runPath",
    "--cli-port-file=$portFile"
)
if ($Headless -and -not $Window) { $javaArguments += '--headless' }
if ($CommandCenterWinCondition) { $javaArguments += '--win-condition=commandCenter' }
# Visible clients all default to the same window title; stamp the run id so two windows can be told
# apart at a glance. Space-free on purpose: Start-Process does not quote arguments for us.
if ($Window -or -not $Headless) {
    $javaArguments += "-Drwx.windowTitle=RWX-$([System.IO.Path]::GetFileName($runPath))"
}

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

[PSCustomObject]@{
    Run = $runPath
    ProcessId = $process.Id
    Headless = ($Headless -and -not $Window)
    WinCondition = if ($CommandCenterWinCondition) { 'commandCenter' } else { 'map' }
    AgentPrompt = "Read $repo\agent-operation\START.md, then use $cmdPath for every game command."
    AgentWritableDirectory = Join-Path $runPath 'tmp'
    ReplayDirectory = Join-Path $runPath 'replays'
}
