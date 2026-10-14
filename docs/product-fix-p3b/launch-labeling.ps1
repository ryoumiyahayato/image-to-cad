param(
    [string]$Reviewer = 'local-reviewer',
    [string]$PatchRoot = ''
)
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python = Join-Path (Split-Path $projectRoot -Parent) '.venv/Scripts/python.exe'
if (-not $PatchRoot) {
    $desktopRoot = Split-Path (Split-Path $projectRoot -Parent) -Parent
    $PatchRoot = Join-Path $desktopRoot 'image-to-cad-p3b-cache/real-v2'
}
$manifest = Join-Path $PSScriptRoot 'real-v2-acceptance.jsonl'
$labels = Join-Path $PSScriptRoot 'labels/v2-ui-acceptance.json'
$ui = Join-Path $projectRoot 'tools/p3b/label_ui.py'
& $python -B $ui --manifest $manifest --labels $labels --patch-root $PatchRoot --annotator $Reviewer
exit $LASTEXITCODE
