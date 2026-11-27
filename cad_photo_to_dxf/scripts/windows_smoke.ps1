param(
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][string]$WorkingDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion
)

$ErrorActionPreference = "Stop"
$exe = (Resolve-Path -LiteralPath $Executable).Path
$work = [System.IO.Path]::GetFullPath($WorkingDirectory)
New-Item -ItemType Directory -Force -Path $work | Out-Null
$version = (Get-Item -LiteralPath $exe).VersionInfo.ProductVersion
if ($version -ne $ExpectedVersion) {
    throw "Executable product version '$version' does not match '$ExpectedVersion'"
}

python (Join-Path $PSScriptRoot "product_smoke.py") --executable $exe --work $work
if ($LASTEXITCODE -ne 0) { throw "Packaged conversion smoke failed" }

# Exercise the same font preparation action exposed by the desktop button.
$fontReport = Join-Path $work "font-install.json"
$fontArguments = @("--install-cad-fonts", "--overwrite", "--report", ('"{0}"' -f $fontReport))
$fontProcess = Start-Process -FilePath $exe -ArgumentList $fontArguments -WorkingDirectory $work -Wait -PassThru
if ($fontProcess.ExitCode -ne 0) { throw "Packaged font preparation failed" }
$fontResult = Get-Content -LiteralPath $fontReport -Raw -Encoding utf8 | ConvertFrom-Json
if ($fontResult.status -ne "prepared") { throw "Font preparation report did not confirm success" }
$fontRegistry = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Software\Microsoft\Windows NT\CurrentVersion\Fonts")
try { $registeredFont = $fontRegistry.GetValue("Noto Sans CJK SC Regular (OpenType)") }
finally { if ($fontRegistry) { $fontRegistry.Dispose() } }
if (-not $registeredFont -or -not (Test-Path -LiteralPath $registeredFont)) {
    throw "Current-user Noto font registration is missing"
}
$fontResources = Join-Path (Split-Path -Parent $exe) "_internal/resources/fonts"
$fontFolder = Split-Path -Parent $registeredFont
$cadFolder = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "librecad/fonts"
foreach ($pair in @(
    @("NotoSansCJKsc-Regular.otf", $registeredFont),
    @("OFL-1.1.txt", (Join-Path $fontFolder "OFL-1.1.txt")),
    @("wqy-unicode.lff", (Join-Path $cadFolder "wqy-unicode.lff")),
    @("WQY-LICENSE-Apache-2.0.txt", (Join-Path $cadFolder "WQY-LICENSE-Apache-2.0.txt"))
)) {
    $source = Join-Path $fontResources $pair[0]
    if (-not (Test-Path -LiteralPath $pair[1])) { throw "Installed font resource missing: $($pair[1])" }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash -ne
        (Get-FileHash -Algorithm SHA256 -LiteralPath $pair[1]).Hash) {
        throw "Installed font resource differs from the bundled file: $($pair[0])"
    }
}
@{ registered_font = $registeredFont; librecad_fonts = $cadFolder; files_match_bundle = $true } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $work "font-smoke.json") -Encoding utf8

# Launch the actual desktop process with the normal Qt platform after CLI checks.
$oldPlatform = $env:QT_QPA_PLATFORM
try {
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    $gui = Start-Process -FilePath $exe -WorkingDirectory $work -PassThru
    Start-Sleep -Seconds 3
    $gui.Refresh()
    if ($gui.HasExited) { throw "GUI exited unexpectedly with code $($gui.ExitCode)" }
    if ($gui.MainWindowHandle -eq 0) { throw "GUI did not create a desktop window" }
    $null = $gui.CloseMainWindow()
    if (-not $gui.WaitForExit(5000)) {
        Stop-Process -Id $gui.Id -Force
        throw "GUI did not exit after normal close"
    }
    @{ gui_started = $true; gui_closed = $true; product_version = $version } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $work "desktop-smoke.json") -Encoding utf8
}
finally {
    if ($oldPlatform) { $env:QT_QPA_PLATFORM = $oldPlatform }
    else { Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue }
}
