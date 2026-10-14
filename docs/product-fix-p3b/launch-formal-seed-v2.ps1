# Prepared for a later explicit start. This task does not execute this launcher.
param([string]$Reviewer = 'local-reviewer')
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path (Split-Path $projectRoot -Parent) '.venv/Scripts/python.exe'
$desktopRoot = Split-Path (Split-Path $projectRoot -Parent) -Parent
$patchRoot = Join-Path $desktopRoot 'image-to-cad-p3b-cache/real-v2-formal-seed-001'
$manifest = Join-Path $PSScriptRoot 'formal-seed-v2-001.jsonl'
$labels = Join-Path $PSScriptRoot 'labels/formal-seed-v2-001.json'
$ui = Join-Path $projectRoot 'tools/p3b/label_ui.py'
& $python -B $ui --mode formal-seed --manifest $manifest --labels $labels --patch-root $patchRoot --annotator $Reviewer
exit $LASTEXITCODE
