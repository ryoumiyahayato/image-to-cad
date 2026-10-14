param(
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][string]$Sample,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion
)

$ErrorActionPreference = "Stop"
$exe = (Resolve-Path -LiteralPath $Executable).Path
$samplePath = (Resolve-Path -LiteralPath $Sample).Path
$work = [System.IO.Path]::GetFullPath($WorkingDirectory)
New-Item -ItemType Directory -Force -Path $work | Out-Null

$output = Join-Path $work "smoke.dxf"
$preview = Join-Path $work "smoke-preview.png"
$report = Join-Path $work "smoke-report.json"
$debugDir = Join-Path $work "debug"

$arguments = @(
    "--headless", "--input", "`"$samplePath`"",
    "--output", "`"$output`"",
    "--preview", "`"$preview`"",
    "--report", "`"$report`"",
    "--debug-dir", "`"$debugDir`"",
    "--paper-size", "A4", "--paper-orientation", "landscape"
)
$process = Start-Process -FilePath $exe -ArgumentList $arguments -Wait -PassThru -WindowStyle Hidden
if ($process.ExitCode -ne 0) {
    throw "Headless smoke test failed with exit code $($process.ExitCode)"
}

foreach ($required in @($output, $preview, $report, (Join-Path $debugDir "corrected.png"), (Join-Path $debugDir "contours.png"))) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Smoke test did not create required artifact: $required"
    }
}

$json = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
if ($json.application_version -ne $ExpectedVersion -or $json.member_counts.straight_lines -le 0) {
    throw "Smoke report failed version or line-count validation"
}
