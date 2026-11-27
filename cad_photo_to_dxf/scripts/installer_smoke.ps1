param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion
)

$ErrorActionPreference = "Stop"
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$work = [System.IO.Path]::GetFullPath($WorkingDirectory)
$installDir = Join-Path $work "installed"
$runDir = Join-Path $work "run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$arguments = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", ('/DIR="{0}"' -f $installDir))
$install = Start-Process -FilePath $installerPath -ArgumentList $arguments -Wait -PassThru
if ($install.ExitCode -ne 0) { throw "Installer failed with exit code $($install.ExitCode)" }
$exe = Join-Path $installDir "CADPhotoToDXF.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "Installed executable not found: $exe" }

try {
    & (Join-Path $PSScriptRoot "windows_smoke.ps1") `
        -Executable $exe -WorkingDirectory $runDir -ExpectedVersion $ExpectedVersion
}
finally {
    $uninstaller = Join-Path $installDir "unins000.exe"
    if (-not (Test-Path -LiteralPath $uninstaller)) { throw "Uninstaller not found" }
    $uninstall = Start-Process -FilePath $uninstaller `
        -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
    if ($uninstall.ExitCode -ne 0) { throw "Uninstaller failed with exit code $($uninstall.ExitCode)" }
    if (Test-Path -LiteralPath $exe) { throw "Executable still exists after uninstall" }
}
@{ install = $true; conversion = $true; gui = $true; uninstall = $true } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $work "installer-smoke.json") -Encoding utf8
