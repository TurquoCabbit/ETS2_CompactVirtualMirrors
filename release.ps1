[CmdletBinding()]
param(
    [string] $Python,
    [string] $Tag
)

$ErrorActionPreference = 'Stop'
$LauncherArgs = @()
if ($Python) {
    $Python = (Get-Command $Python -CommandType Application).Source
} else {
    $Python = (Get-Command py -CommandType Application).Source
    $LauncherArgs = @('-3.12-64')
}

function Invoke-Checked {
    param([string] $Executable, [string[]] $Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Executable failed with exit code $LASTEXITCODE."
    }
}

Push-Location $PSScriptRoot
try {
    Invoke-Checked $Python ($LauncherArgs + @('-c', 'import platform, sys; assert sys.version_info[:2] == (3, 12) and platform.machine() == ''AMD64'', ''Use Windows x64 Python 3.12.'''))
    $Version = Invoke-Checked $Python ($LauncherArgs + @('-c', 'from mirrors.release_info import VERSION; print(VERSION)'))
    if ($Tag) {
        if ($Tag -cne "v$Version") { throw "Release tag must be v$Version." }
        $TaggedCommit = Invoke-Checked git @('rev-list', '-n', '1', $Tag)
        $HeadCommit = Invoke-Checked git @('rev-parse', 'HEAD')
        $Changes = Invoke-Checked git @('status', '--porcelain')
        if (!$TaggedCommit -or $TaggedCommit -ne $HeadCommit -or $Changes) {
            throw 'A release build requires a clean checkout at the matching tag.'
        }
    }

    $Environment = Join-Path $PSScriptRoot '.runtime\release-venv'
    $ReleasePython = Join-Path $Environment 'Scripts\python.exe'
    if (!(Test-Path -LiteralPath $ReleasePython)) {
        Invoke-Checked $Python ($LauncherArgs + @('-m', 'venv', $Environment))
    }
    Invoke-Checked $ReleasePython @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'requirements-release.txt')
    Invoke-Checked $ReleasePython @('-m', 'pytest', '-q')

    $Stage = Join-Path $PSScriptRoot ".runtime\release-v$Version"
    $Output = Join-Path $PSScriptRoot "dist\v$Version"
    $OriginalPath = $env:Path
    try {
        $env:Path = "$(Split-Path -Parent $ReleasePython);$env:SystemRoot\System32;$env:SystemRoot"
        Invoke-Checked $ReleasePython @('-m', 'PyInstaller', '--noconfirm', '--clean', '--workpath',
            (Join-Path $Stage 'build'), '--distpath', $Stage, 'release.spec')
    } finally {
        $env:Path = $OriginalPath
    }

    $Exe = "ETS2-Configurable-Mirrors-v$Version-windows-x64.exe"
    $Licenses = Join-Path $Stage 'licenses'
    New-Item -ItemType Directory -Force -Path $Licenses | Out-Null
    Copy-Item -LiteralPath 'LICENSE', 'THIRD_PARTY_NOTICES.md' -Destination $Licenses
    $PythonLicense = Invoke-Checked $ReleasePython @('-c', 'from pathlib import Path; import sys; print(Path(sys.base_prefix) / ''LICENSE.txt'')')
    Copy-Item -LiteralPath $PythonLicense -Destination (Join-Path $Licenses 'Python-LICENSE.txt')
    $PyInstallerLicense = Invoke-Checked $ReleasePython @('-c', 'from importlib.metadata import distribution; d = distribution(''pyinstaller''); print(d.locate_file(next(p for p in d.files if p.name == ''COPYING.txt'' and ''.dist-info/'' in p.as_posix())))')
    Copy-Item -LiteralPath $PyInstallerLicense -Destination (Join-Path $Licenses 'PyInstaller-COPYING.txt')
    $PythonVersion = Invoke-Checked $ReleasePython @('-c', 'import platform; print(platform.python_version())')
    Set-Content -LiteralPath (Join-Path $Licenses 'build-info.txt') -Encoding ascii -Value @(
        "App $Version", "CPython $PythonVersion (Windows x64)", "Source tag: $Tag")
    $Notices = "ETS2-Configurable-Mirrors-v$Version-notices.zip"
    Compress-Archive -Path (Join-Path $Licenses '*') -DestinationPath (Join-Path $Stage $Notices) -Force

    $Artifacts = @($Exe, $Notices)
    if ($Tag) {
        $Source = "ETS2-Configurable-Mirrors-v$Version-source.zip"
        Invoke-Checked git @('archive', '--format=zip', "--output=$(Join-Path $Stage $Source)",
            "--prefix=ETS2-Configurable-Mirrors-v$Version/", $Tag)
        $Artifacts += $Source
    }
    New-Item -ItemType Directory -Force -Path $Output | Out-Null
    $ChecksumPath = Join-Path $Output 'SHA256SUMS.txt'
    if (Test-Path -LiteralPath $ChecksumPath) {
        Remove-Item -LiteralPath $ChecksumPath
    }
    foreach ($Artifact in $Artifacts) {
        Copy-Item -LiteralPath (Join-Path $Stage $Artifact) -Destination $Output -Force
    }

    $ExePath = Join-Path $Output $Exe
    $OriginalPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:Path = "$env:SystemRoot\System32;$env:SystemRoot"
        $env:QT_QPA_PLATFORM = 'windows'
        $Smoke = Start-Process -FilePath $ExePath -WorkingDirectory $Output -ArgumentList '--version' `
            -WindowStyle Hidden -PassThru
        if (!$Smoke.WaitForExit(45000)) {
            $Smoke.Kill()
            throw 'The packaged editor startup check timed out.'
        }
        if ($Smoke.ExitCode -ne 0) {
            throw "The packaged editor startup check failed with exit code $($Smoke.ExitCode)."
        }
    } finally {
        $env:Path = $OriginalPath
        $env:QT_QPA_PLATFORM = $OriginalPlatform
    }
    $Hash = (Get-FileHash -LiteralPath $ExePath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath $ChecksumPath -Encoding ascii -Value "$Hash *$Exe"
    Write-Host "Built release files in $Output"
} finally {
    Pop-Location
}
