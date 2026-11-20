[CmdletBinding()]
param(
    # Rollout spec (JSON). See RWX_RL_ROLLOUT.md for every field.
    [Parameter(Mandatory)]
    [ValidateNotNullOrEmpty()]
    [string]$Spec,

    # Output directory; defaults to the spec's own "out". The process writes its materials here.
    [string]$Out,

    # Override the number of ticks; useful for a fast smoke run (e.g. -MaxTicks 600).
    [int]$MaxTicks = 0,

    # Replay the recording back at maximum speed and report engine checksum mismatches.
    [switch]$Verify,

    # Keep the run's stdout/stderr logs (always kept, this only prints their paths).
    [switch]$Quiet,

    [ValidateRange(256, 8192)]
    [int]$MaxHeapMiB = 1536
)

$ErrorActionPreference = 'Stop'

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$dist = Join-Path $repo 'desktop\build\headless\lib'
if (-not (Test-Path -LiteralPath $dist)) {
    throw "Missing runtime distribution: $dist. Build it first with .\gradlew.bat :desktop:headlessDist"
}
$specPath = (Resolve-Path -LiteralPath $Spec).Path
$specObject = Get-Content -LiteralPath $specPath -Raw | ConvertFrom-Json
$runPath = if ($Out) { [System.IO.Path]::GetFullPath($Out) } else { [System.IO.Path]::GetFullPath($specObject.out) }
if (-not $runPath) { throw "The spec needs an 'out' directory, or pass -Out" }
if ($MaxTicks -gt 0) { $specObject.limits.maxTicks = $MaxTicks }
# The launcher owns "out", so a spec can be reused for many runs by overriding it here.
$specObject.out = $runPath
New-Item -ItemType Directory -Path $runPath -Force | Out-Null
$effectiveSpec = Join-Path $runPath 'spec.json'
[System.IO.File]::WriteAllText($effectiveSpec, ($specObject | ConvertTo-Json -Depth 8), (New-Object System.Text.UTF8Encoding($false)))

$java = (Get-Command java -ErrorAction Stop).Source
$javaArguments = @(
    '-Xms256m', "-Xmx$($MaxHeapMiB)m", '-Dfile.encoding=UTF-8',
    '-Dorg.lwjgl.opengl.contextAPI=native', '-Dorg.lwjgl.system.stackSize=512',
    '--enable-native-access=ALL-UNNAMED', '--sun-misc-unsafe-memory-access=allow',
    "-Drwx.repoDir=$repo", "-Drwx.assetsDir=$(Join-Path $repo 'assets')",
    '-cp', (Join-Path $dist '*'),
    'io.github.rwx.DesktopMain', '--no-steam', "--rollout-config=$effectiveSpec",
    "--data-dir=$runPath"
)

$sw = [System.Diagnostics.Stopwatch]::StartNew()
# Start-Process 会把 -ArgumentList 用空格拼成命令行，含空格的路径必须自己加引号
$javaArguments = $javaArguments | ForEach-Object { if ("$_" -match '\s') { '"' + $_ + '"' } else { "$_" } }
$process = Start-Process -FilePath $java -ArgumentList $javaArguments -WorkingDirectory $runPath `
    -RedirectStandardOutput (Join-Path $runPath 'rollout.log') `
    -RedirectStandardError (Join-Path $runPath 'rollout.err.log') -PassThru -Wait
$sw.Stop()

$resultFile = Join-Path $runPath 'result.json'
if (-not (Test-Path -LiteralPath $resultFile)) {
    Get-Content -LiteralPath (Join-Path $runPath 'rollout.log') -Tail 25
    throw "Rollout wrote no result.json (exit $($process.ExitCode)); see $runPath\rollout.log"
}
$result = Get-Content -LiteralPath $resultFile -Raw | ConvertFrom-Json

$verifyReport = $null
if ($Verify -and $result.replay) {
    $replay = $result.replay
    $checkArgs = @(
        '-Xmx1536m', '-Dfile.encoding=UTF-8',
        '--enable-native-access=ALL-UNNAMED', '--sun-misc-unsafe-memory-access=allow',
        "-Drwx.repoDir=$repo", "-Drwx.assetsDir=$(Join-Path $repo 'assets')",
        '-cp', (Join-Path $dist '*'),
        'io.github.rwx.DesktopMain', '--no-steam', "--replay-check=$replay"
    )
    $check = Start-Process -FilePath $java -ArgumentList ($checkArgs | ForEach-Object { if ("$_" -match '\s') { '"' + $_ + '"' } else { "$_" } }) -WorkingDirectory $runPath `
        -RedirectStandardOutput (Join-Path $runPath 'replay-check.log') `
        -RedirectStandardError (Join-Path $runPath 'replay-check.err.log') -PassThru -Wait
    $checkFile = "$replay.check.json"
    if (Test-Path -LiteralPath $checkFile) {
        $verifyReport = Get-Content -LiteralPath $checkFile -Raw | ConvertFrom-Json
    }
    if ($check.ExitCode -ne 0) {
        Write-Host "Replay check FAILED (exit $($check.ExitCode)); see $runPath\replay-check.log" -ForegroundColor Yellow
    }
}

if (-not $Quiet) {
    [PSCustomObject]@{
        Run = $runPath
        Map = $result.map
        Outcome = $result.outcome
        Ticks = $result.ticks
        GameSeconds = [math]::Round($result.gameMs / 1000.0, 2)
        WallSeconds = [math]::Round($result.wallMs / 1000.0, 2)
        ProcessSeconds = [math]::Round($sw.Elapsed.TotalSeconds, 2)
        TicksPerSecond = $result.ticksPerSecond
        Replay = $result.replay
        Samples = (Join-Path $runPath 'samples.jsonl')
        Result = $resultFile
        ReplayConsistent = if ($verifyReport) { $verifyReport.consistent } else { $null }
        ReplayDesyncs = if ($verifyReport) { $verifyReport.desyncs } else { $null }
    }
}
if ($result.decisive -ne $true -and -not $Quiet) {
    Write-Host "Match was not decisive ($($result.outcome)); raise limits.maxTicks or maxWallSeconds." -ForegroundColor Yellow
}
if ($Verify -and $verifyReport -and -not $verifyReport.consistent -and -not $Quiet) {
    Write-Host "Replay desynced: $($verifyReport.desyncs) checksum mismatches." -ForegroundColor Red
}
