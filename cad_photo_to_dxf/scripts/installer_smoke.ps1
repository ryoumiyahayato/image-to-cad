param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$Sample,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory
)

$ErrorActionPreference = "Stop"
$work = [System.IO.Path]::GetFullPath($WorkingDirectory)
$installDir = Join-Path $work "installed"
$runDir = Join-Path $work "run"
$logPath = Join-Path $work "installer-smoke.log"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

function Write-SmokeLog([string]$Message) {
    $timestamp = [DateTime]::UtcNow.ToString("o")
    "$timestamp $Message" | Tee-Object -FilePath $logPath -Append
}

$gui = $null
try {
    Write-SmokeLog "Resolving installer path: $Installer"
    $installerPath = (Resolve-Path -LiteralPath $Installer).Path
    $samplePath = (Resolve-Path -LiteralPath $Sample).Path

    Write-SmokeLog "Starting silent install: $installerPath"
    $installArguments = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/DIR=$installDir"
    )
    $install = Start-Process -FilePath $installerPath -ArgumentList $installArguments -Wait -PassThru
    Write-SmokeLog "Installer exit code: $($install.ExitCode)"
    if ($install.ExitCode -ne 0) {
        throw "Installer failed with exit code $($install.ExitCode)"
    }

    $exe = Join-Path $installDir "CADPhotoToDXF.exe"
    if (-not (Test-Path -LiteralPath $exe)) {
        throw "Installed executable not found: $exe"
    }
    Write-SmokeLog "Installed executable found: $exe"

    Write-SmokeLog "Starting installed headless smoke test"
    & (Join-Path $PSScriptRoot "windows_smoke.ps1") `
        -Executable $exe `
        -Sample $samplePath `
        -WorkingDirectory $runDir
    Write-SmokeLog "Installed headless smoke test passed"

    Write-SmokeLog "Starting installed GUI smoke test"
    $gui = Start-Process -FilePath $exe -PassThru
    Start-Sleep -Seconds 5
    $gui.Refresh()
    if ($gui.HasExited) {
        throw "Installed GUI exited unexpectedly with code $($gui.ExitCode)"
    }
    Write-SmokeLog "Installed GUI remained running; process id $($gui.Id)"

    $closed = $gui.CloseMainWindow()
    Write-SmokeLog "CloseMainWindow returned: $closed"
    if (-not $closed -or -not $gui.WaitForExit(5000)) {
        Write-SmokeLog "GUI did not close cleanly; forcing process termination"
        Stop-Process -Id $gui.Id -Force -ErrorAction SilentlyContinue
        $gui.WaitForExit()
    }
    Write-SmokeLog "Installed GUI process stopped"
    $gui = $null

    $uninstaller = Join-Path $installDir "unins000.exe"
    if (-not (Test-Path -LiteralPath $uninstaller)) {
        throw "Uninstaller not found: $uninstaller"
    }
    Write-SmokeLog "Starting silent uninstall: $uninstaller"
    $uninstall = Start-Process -FilePath $uninstaller -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
    Write-SmokeLog "Uninstaller exit code: $($uninstall.ExitCode)"
    if ($uninstall.ExitCode -ne 0) {
        throw "Uninstaller failed with exit code $($uninstall.ExitCode)"
    }
    if (Test-Path -LiteralPath $exe) {
        throw "Executable still exists after uninstall"
    }
    Write-SmokeLog "Install, launch, and uninstall smoke test passed"
}
catch {
    Write-SmokeLog "FAILED: $($_.Exception.Message)"
    throw
}
finally {
    if ($null -ne $gui -and -not $gui.HasExited) {
        Write-SmokeLog "Final cleanup: forcing GUI process termination"
        Stop-Process -Id $gui.Id -Force -ErrorAction SilentlyContinue
    }
}
