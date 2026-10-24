param([string]$Python = 'python')

$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'cad_photo_to_dxf'
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = $source
    & $Python (Join-Path $source 'main.py') @args
    exit $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
