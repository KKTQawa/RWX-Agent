[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Run,

    [Parameter(Mandatory)]
    # Every accepted case ships its own managed prompt at evaluate\micro\<Case>\prompt_single.md.
    [ValidateSet('CASE1-duel', 'CASE2-LTE', 'CASE3-Transport', 'CASE4-Retreat')]
    [string]$Case,

    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$CaseArgs,

    [ValidateRange(256, 4096)]
    [int]$MaxHeapMiB = 768,

    [switch]$Window
)

$ErrorActionPreference = 'Stop'

if ($CaseArgs -match '[\r\n]' -or $CaseArgs -match '(^|,)out=') {
    throw 'CaseArgs must be one comma-separated line and must not contain out=; the launcher owns the output directory.'
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runPath = [System.IO.Path]::GetFullPath($Run)
$repoPrefix = $repo.TrimEnd('\') + '\'
if ($runPath.StartsWith($repoPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Run must be outside the repository so it cannot share runtime files: $runPath"
}
if (Test-Path -LiteralPath $runPath) {
    throw "Run directory already exists; choose a new run id instead of reusing it: $runPath"
}

$headless = Join-Path $repo 'desktop\build\headless'
if (-not (Test-Path -LiteralPath (Join-Path $headless 'lib'))) {
    throw "Missing runtime distribution: $headless. Build it first with .\gradlew.bat :desktop:headlessDist"
}
if ($null -eq (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'python is required by <run>\rwx.cmd but was not found on PATH.'
}

$agentPrompt = Join-Path $repo "evaluate\micro\$Case\prompt_single.md"
if (-not (Test-Path -LiteralPath $agentPrompt)) {
    throw "Missing managed Agent prompt for $Case; add $agentPrompt before handing this case to an Agent."
}

New-Item -ItemType Directory -Path $runPath | Out-Null
@('tmp', 'replays', 'commands', 'events-live', 'logs', 'micro-output') |
    ForEach-Object { New-Item -ItemType Directory -Path (Join-Path $runPath $_) | Out-Null }

$portFile = Join-Path $runPath 'port'
$cmdPath = Join-Path $runPath 'rwx.cmd'
$cliPath = Join-Path $repo 'agent-operation\tools\rwx-cli.py'
@"
@echo off
python "$cliPath" --port-file "%~dp0port" --timeout 60 %*
"@ | Set-Content -LiteralPath $cmdPath -Encoding ascii

$microOutput = Join-Path $runPath 'micro-output'
$effectiveCaseArgs = "$CaseArgs,out=$microOutput"
$manifest = [ordered]@{
    schema = 'rwx-micro-managed-run-v1'
    createdAt = [DateTime]::UtcNow.ToString('o')
    run = $runPath
    case = $Case
    caseArgs = $CaseArgs
    outputRoot = $microOutput
    maxHeapMiB = $MaxHeapMiB
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runPath 'micro-run.json') -Encoding utf8

$java = Get-Command java -ErrorAction Stop
$javaArguments = @(
    '-Xms256m', "-Xmx$($MaxHeapMiB)m", '-Dfile.encoding=UTF-8',
    '-Dorg.lwjgl.opengl.contextAPI=native', '-Dorg.lwjgl.system.stackSize=512',
    '--enable-native-access=ALL-UNNAMED', '--sun-misc-unsafe-memory-access=allow',
    "-Dlaunch.dir=$runPath", "-Drwx.repoDir=$repo", "-Drwx.log.dir=$(Join-Path $runPath 'logs')",
    "-Drwx.evaluate.dir=$(Join-Path $runPath 'events-live')",
    "-Drwx.cli.recordingDir=$(Join-Path $runPath 'commands')", '-Drwx.cli.terminal=false',
    "-Drwx.assetsDir=$(Join-Path $repo 'assets')", '-cp', (Join-Path $headless 'lib\*'),
    'io.github.rwx.DesktopMain', '--no-steam', '--evaluate', $Case, '--case-args', $effectiveCaseArgs, '--micro-lobby',
    "--data-dir=$runPath", "--cli-port-file=$portFile"
)
if (-not $Window) { $javaArguments += '--headless' }

$stdout = Join-Path $runPath 'logs\game.stdout.log'
$stderr = Join-Path $runPath 'logs\game.stderr.log'
$process = Start-Process -FilePath $java.Source -ArgumentList $javaArguments -WorkingDirectory $runPath `
    -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru

$ready = $false
$deadline = [DateTime]::UtcNow.AddSeconds(90)
while ([DateTime]::UtcNow -lt $deadline -and -not $process.HasExited) {
    if (Test-Path -LiteralPath $portFile) {
        $lobby = & $cmdPath rwx-micro-lobby-status 2>$null
        if ($LASTEXITCODE -eq 0 -and $lobby -match "ok: micro lobby case=$([regex]::Escape($Case)) phase=lobby") {
            $ready = $true; break
        }
    }
    Start-Sleep -Milliseconds 250
}
if (-not $ready) {
    throw "RWX micro run did not reach its lobby within 90 seconds. Inspect $stdout and $stderr; process id=$($process.Id)."
}

[PSCustomObject]@{
    Run = $runPath
    ProcessId = $process.Id
    Case = $Case
    CaseArgs = $CaseArgs
    AgentPrompt = $agentPrompt
    AgentWritableDirectory = Join-Path $runPath 'tmp'
    EvidenceDirectory = $microOutput
}
