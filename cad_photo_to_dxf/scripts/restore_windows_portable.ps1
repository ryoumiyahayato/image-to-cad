param(
    [switch] $NoPause,
    [switch] $NoLaunch,
    [string] $ReportPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$baseDirectory = [IO.Path]::GetFullPath($PSScriptRoot)
$temporaryArchive = $null
$stagingDirectory = $null
$exitCode = 1
$result = [ordered]@{
    schema = 'cadphoto-portable-restoration-result-v2'
    status = 'FAILED'
    code = 'UNEXPECTED_ERROR'
    message = ''
    archive_verified = $false
    files_verified = 0
    archive_reused = $false
    directory_reused = $false
    launched = $false
    process_id = $null
    source_commit = $null
    original_bytes = $null
    original_sha256 = $null
    extracted_directory = $null
    execution_policy_change = 'Child PowerShell process only; no persistent policy changes'
}

function Stop-Restore([string] $Code, [string] $Message) {
    throw "$Code|$Message"
}

function Assert-RelativeName([string] $Value, [switch] $Basename) {
    if (-not $Value -or $Value.Contains('\') -or [IO.Path]::IsPathRooted($Value)) {
        Stop-Restore 'MANIFEST_INVALID' '恢复清单含不安全的文件名。'
    }
    $components = $Value.Split('/')
    if ($Basename -and $components.Count -ne 1) {
        Stop-Restore 'MANIFEST_INVALID' '恢复清单的文件名必须位于当前文件夹。'
    }
    foreach ($component in $components) {
        if (-not $component -or $component -eq '.' -or $component -eq '..' -or
            $component -match '[<>:"|?*\x00-\x1f]' -or $component -match '[ .]$' -or
            $component -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') {
            Stop-Restore 'MANIFEST_INVALID' '恢复清单含 Windows 不支持的文件名。'
        }
    }
}

function Assert-NoReparsePoint([string] $Path) {
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        Stop-Restore 'EXISTING_DIRECTORY_CONFLICT' '发现链接目录或文件，请在新的普通文件夹中恢复。原文件已保留。'
    }
}

function Get-FileSha256([string] $Path) {
    # The launcher uses inbox Windows PowerShell. Do not depend on module
    # discovery inherited from PowerShell 7 or another parent process.
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = $null
    try {
        $algorithm = [Security.Cryptography.SHA256]::Create()
        return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    } finally {
        if ($null -ne $algorithm) { $algorithm.Dispose() }
        $stream.Dispose()
    }
}

function Assert-File([string] $Path, [long] $Bytes, [string] $Hash, [string] $Code) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Stop-Restore $Code ('文件不存在：' + [IO.Path]::GetFileName($Path))
    }
    Assert-NoReparsePoint $Path
    if ((Get-Item -LiteralPath $Path).Length -ne $Bytes -or
        (Get-FileSha256 $Path) -cne $Hash) {
        Stop-Restore $Code ('文件不完整或内容不同，原文件已保留：' + [IO.Path]::GetFileName($Path))
    }
}

function Assert-ExtractedFiles([string] $Directory, $Files) {
    Assert-NoReparsePoint $Directory
    foreach ($file in $Files) {
        $path = Join-Path $Directory $file.path
        $parent = [IO.Path]::GetDirectoryName($path)
        while ($parent.Length -gt $Directory.Length) {
            if (Test-Path -LiteralPath $parent) { Assert-NoReparsePoint $parent }
            $parent = [IO.Path]::GetDirectoryName($parent)
        }
        Assert-File $path $file.bytes $file.sha256 'EXISTING_DIRECTORY_CONFLICT'
    }
}

try {
    Write-Host '正在检查程序包，请稍候。'
    $manifestPath = Join-Path $baseDirectory 'PORTABLE_RESTORE_MANIFEST.json'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        Stop-Restore 'MANIFEST_MISSING' '缺少 PORTABLE_RESTORE_MANIFEST.json，请与恢复脚本放在同一文件夹。'
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schema -cne 'cadphoto-portable-recovery-v2' -or
        $manifest.source_commit -cnotmatch '^[0-9a-f]{40}$' -or
        $manifest.original_sha256 -cnotmatch '^[0-9a-f]{64}$' -or
        [long] $manifest.original_bytes -le 0 -or
        $manifest.executable_relative_path -cne 'CADPhotoToDXF.exe') {
        Stop-Restore 'MANIFEST_INVALID' '恢复清单版本或校验信息无效。'
    }
    Assert-RelativeName $manifest.original_file -Basename
    Assert-RelativeName $manifest.extract_directory -Basename
    $fileMap = [Collections.Generic.Dictionary[string,object]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($file in @($manifest.files)) {
        Assert-RelativeName $file.path
        if ([long] $file.bytes -lt 0 -or $file.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
            $fileMap.ContainsKey($file.path)) {
            Stop-Restore 'MANIFEST_INVALID' '恢复清单含无效或重复的程序文件。'
        }
        $fileMap.Add($file.path, $file)
    }
    if (-not $fileMap.ContainsKey('CADPhotoToDXF.exe')) {
        Stop-Restore 'MANIFEST_INVALID' '恢复清单未包含主程序。'
    }
    $result.source_commit = $manifest.source_commit
    $result.original_bytes = $manifest.original_bytes
    $result.original_sha256 = $manifest.original_sha256
    $outputArchive = Join-Path $baseDirectory $manifest.original_file
    $outputDirectory = Join-Path $baseDirectory $manifest.extract_directory
    $result.extracted_directory = $outputDirectory

    if (Test-Path -LiteralPath $outputArchive) {
        Assert-File $outputArchive $manifest.original_bytes $manifest.original_sha256 'EXISTING_ZIP_CONFLICT'
        $result.archive_reused = $true
    } else {
        $seenParts = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        [long] $partBytes = 0
        foreach ($part in @($manifest.parts)) {
            Assert-RelativeName $part.file -Basename
            if (-not $seenParts.Add($part.file) -or [long] $part.bytes -le 0 -or
                $part.sha256 -cnotmatch '^[0-9a-f]{64}$') {
                Stop-Restore 'MANIFEST_INVALID' '恢复清单含无效或重复分卷。'
            }
            $partPath = Join-Path $baseDirectory $part.file
            if (-not (Test-Path -LiteralPath $partPath -PathType Leaf)) {
                Stop-Restore 'MISSING_PART' ('缺少分卷：' + $part.file + '。请取得全部分卷后重试。')
            }
            Assert-File $partPath $part.bytes $part.sha256 'PART_MISMATCH'
            $partBytes += [long] $part.bytes
        }
        if ($seenParts.Count -eq 0 -or $partBytes -ne [long] $manifest.original_bytes) {
            Stop-Restore 'MANIFEST_INVALID' '分卷总大小与恢复清单不符。'
        }
        Write-Host '分卷检查完成，正在恢复完整程序包。'
        $temporaryArchive = Join-Path $baseDirectory ('.cadphoto-assembling-' + [guid]::NewGuid().ToString('N') + '.tmp')
        $target = [IO.File]::Open($temporaryArchive, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try {
            foreach ($part in $manifest.parts) {
                $source = [IO.File]::OpenRead((Join-Path $baseDirectory $part.file))
                try { $source.CopyTo($target) } finally { $source.Dispose() }
            }
        } finally { $target.Dispose() }
        Assert-File $temporaryArchive $manifest.original_bytes $manifest.original_sha256 'JOINED_ZIP_MISMATCH'
        [IO.File]::Move($temporaryArchive, $outputArchive)
        $temporaryArchive = $null
    }
    $result.archive_verified = $true

    if (Test-Path -LiteralPath $outputDirectory) {
        if (-not (Test-Path -LiteralPath $outputDirectory -PathType Container)) {
            Stop-Restore 'EXISTING_DIRECTORY_CONFLICT' '解压位置已有不同文件，原文件已保留。请在新文件夹恢复。'
        }
        Assert-ExtractedFiles $outputDirectory $manifest.files
        $result.directory_reused = $true
    } else {
        Write-Host '程序包检查完成，正在解压并核对程序文件。'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $stagingDirectory = Join-Path $baseDirectory ('.cadphoto-extracting-' + [guid]::NewGuid().ToString('N'))
        [IO.Directory]::CreateDirectory($stagingDirectory) | Out-Null
        $zip = [IO.Compression.ZipFile]::OpenRead($outputArchive)
        try {
            $seenEntries = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
            foreach ($entry in $zip.Entries) {
                if ($entry.FullName.EndsWith('/')) {
                    Assert-RelativeName ($entry.FullName.TrimEnd('/'))
                    continue
                }
                Assert-RelativeName $entry.FullName
                if (-not $seenEntries.Add($entry.FullName) -or -not $fileMap.ContainsKey($entry.FullName)) {
                    Stop-Restore 'ARCHIVE_CONTENT_MISMATCH' '程序包包含重复文件或清单以外的文件。'
                }
                $expected = $fileMap[$entry.FullName]
                if ($entry.FullName -cne $expected.path -or $entry.Length -ne [long] $expected.bytes) {
                    Stop-Restore 'ARCHIVE_CONTENT_MISMATCH' '程序包内文件与恢复清单不符。'
                }
                $path = Join-Path $stagingDirectory $entry.FullName
                [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path)) | Out-Null
                $target = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
                $source = $entry.Open()
                try { $source.CopyTo($target) } finally { $source.Dispose(); $target.Dispose() }
            }
            if ($seenEntries.Count -ne $fileMap.Count) {
                Stop-Restore 'ARCHIVE_CONTENT_MISMATCH' '程序包内缺少恢复清单要求的文件。'
            }
        } finally { $zip.Dispose() }
        Assert-ExtractedFiles $stagingDirectory $manifest.files
        [IO.Directory]::Move($stagingDirectory, $outputDirectory)
        $stagingDirectory = $null
    }
    $result.files_verified = $fileMap.Count
    $result.status = 'PREPARED'
    $result.code = 'OK'
    $result.message = '程序已验证并恢复，可以使用。'
    if (-not $NoLaunch) {
        $executable = Join-Path $outputDirectory $manifest.executable_relative_path
        $process = Start-Process -FilePath $executable -WorkingDirectory $outputDirectory -PassThru
        if ($process.WaitForExit(2500)) {
            Stop-Restore 'APPLICATION_EXITED' ('程序打开后提前退出，退出码：' + $process.ExitCode + '。恢复后的文件已保留。')
        }
        $result.launched = $true
        $result.process_id = $process.Id
        $result.message = '程序已恢复并打开。请在应用中准备 CAD 字体，再打开结果图。'
    }
    Write-Host $result.message
    $exitCode = 0
} catch {
    $message = $_.Exception.Message
    $result.status = 'FAILED'
    if ($message.Contains('|')) {
        $pieces = $message.Split('|', 2)
        $result.code = $pieces[0]
        $result.message = $pieces[1]
    } else {
        $result.code = 'UNEXPECTED_ERROR'
        $result.message = '恢复失败，原文件已保留。原因：' + $message
    }
    Write-Host $result.message -ForegroundColor Red
} finally {
    if ($temporaryArchive -and (Test-Path -LiteralPath $temporaryArchive)) {
        Remove-Item -LiteralPath $temporaryArchive -Force
    }
    if ($stagingDirectory -and (Test-Path -LiteralPath $stagingDirectory)) {
        Remove-Item -LiteralPath $stagingDirectory -Recurse -Force
    }
    if (-not $ReportPath) {
        $ReportPath = Join-Path $baseDirectory ('Restore-result-' + [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss-fffffff') + '.json')
    }
    try {
        $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $ReportPath -Encoding UTF8
    } catch {
        Write-Host '恢复日志无法写入，请保留窗口中的错误说明。' -ForegroundColor Yellow
    }
    if (-not $NoPause) {
        Write-Host '按 Enter 关闭此窗口。'
        [void] (Read-Host)
    }
}
exit $exitCode
