param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$Sample,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion
)

$ErrorActionPreference = "Stop"
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$samplePath = (Resolve-Path -LiteralPath $Sample).Path
$work = [System.IO.Path]::GetFullPath($WorkingDirectory)
$installDir = Join-Path $work "installed"
$runDir = Join-Path $work "run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

$install = Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=$installDir" -Wait -PassThru -WindowStyle Hidden
if ($install.ExitCode -ne 0) {
    throw "Installer failed with exit code $($install.ExitCode)"
}

$exe = Join-Path $installDir "CADPhotoToDXF.exe"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Installed executable not found: $exe"
}

& (Join-Path $PSScriptRoot "windows_smoke.ps1") `
    -Executable $exe `
    -Sample $samplePath `
    -WorkingDirectory $runDir `
    -ExpectedVersion $ExpectedVersion

$gui = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 3
if ($gui.HasExited) {
    throw "Installed GUI exited unexpectedly with code $($gui.ExitCode)"
}
$null = $gui.CloseMainWindow()
if (-not $gui.WaitForExit(5000)) {
    Stop-Process -Id $gui.Id -Force
    $gui.WaitForExit()
}

$uninstaller = Join-Path $installDir "unins000.exe"
if (-not (Test-Path -LiteralPath $uninstaller)) {
    throw "Uninstaller not found: $uninstaller"
}
$uninstall = Start-Process -FilePath $uninstaller -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru -WindowStyle Hidden
if ($uninstall.ExitCode -ne 0) {
    throw "Uninstaller failed with exit code $($uninstall.ExitCode)"
}
if (Test-Path -LiteralPath $exe) {
    throw "Executable still exists after uninstall"
}
