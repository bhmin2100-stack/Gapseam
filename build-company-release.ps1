[CmdletBinding()]
param([switch]$Clean)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSCommandPath
Set-Location $root
$srcPath = Join-Path $root "src"
$env:PYTHONPATH = $srcPath

function Write-Utf8NoBom($Path, $Content) {
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

function Remove-BuildInfoBytecode {
    $cacheDir = Join-Path $root "src\gapsim\__pycache__"
    Get-ChildItem -LiteralPath $cacheDir -Filter "build_info*.pyc" -File -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
$null = & $python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed." }
}

$version = (& $python -c "import gapsim; print(gapsim.__version__)").Trim()
if (-not $version) { throw "Could not read gapsim.__version__." }

$pyprojectVersion = (& $python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])").Trim()
if ($pyprojectVersion -ne $version) { throw "Version mismatch: gapsim=$version pyproject=$pyprojectVersion" }

$buildInfo = Join-Path $root "src\gapsim\build_info.py"
$originalBuildInfo = Get-Content -LiteralPath $buildInfo -Raw
$buildDate = (Get-Date).ToUniversalTime().ToString("o")
$commit = (git rev-parse HEAD).Trim()
$buildId = "company-local-" + (Get-Date -Format "yyyyMMddHHmmss")
$distPath = Join-Path $root "dist"
$zipPath = Join-Path $distPath "Gapseam.zip"
$manifestPath = Join-Path $distPath "version.json"
$smokeFile = Join-Path ([System.IO.Path]::GetTempPath()) ("gapseam-build-info-" + [guid]::NewGuid().ToString("N") + ".json")

try {
    $companyBuildInfo = @"
from __future__ import annotations

APP_VERSION = "$version"
BUILD_COMMIT = "$commit"
BUILD_ID = "$buildId"
BUILD_DATE = "$buildDate"
UPDATE_CHANNEL = "company"
"@
    Write-Utf8NoBom $buildInfo $companyBuildInfo
    Remove-BuildInfoBytecode

    $embeddedVersion = (& $python -c "from gapsim import __version__; from gapsim.build_info import APP_VERSION, UPDATE_CHANNEL; print(f'{__version__}|{APP_VERSION}|{UPDATE_CHANNEL}')").Trim()
    if ($embeddedVersion -ne "$version|$version|company") { throw "Build version validation failed: $embeddedVersion" }

    if ($Clean) {
        Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $distPath | Out-Null
    Remove-Item -Force $zipPath -ErrorAction SilentlyContinue
    Remove-Item -Force $manifestPath -ErrorAction SilentlyContinue

    & $python -m PyInstaller --clean --noconfirm GFE.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $gfeDir = Join-Path $distPath "GFE"
    $gfeExe = Join-Path $gfeDir "GFE.exe"
    if (-not (Test-Path $gfeExe)) { throw "The built GFE.exe was not found: $gfeExe" }

    $process = Start-Process -FilePath $gfeExe -ArgumentList @("--build-info-json", $smokeFile) -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit(30000)) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        throw "Build smoke test timed out."
    }
    if ($process.ExitCode -ne 0) { throw "Build smoke test failed with exit code $($process.ExitCode)." }
    if (-not (Test-Path $smokeFile)) { throw "Build smoke test did not create metadata file." }

    $smoke = Get-Content -LiteralPath $smokeFile -Raw | ConvertFrom-Json
    if ($smoke.package_version -ne $version -or $smoke.app_version -ne $version -or $smoke.update_channel -ne "company") {
        throw "Company channel was not embedded in GFE.exe. Smoke metadata: $(Get-Content -LiteralPath $smokeFile -Raw)"
    }

    Compress-Archive -LiteralPath $gfeDir -DestinationPath $zipPath -Force
    if (-not (Test-Path $zipPath)) { throw "ZIP creation failed: $zipPath" }
    $sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
    $size = (Get-Item -LiteralPath $zipPath).Length
    $notes = "Company Release Manager build for Gapseam $version"

    $manifest = [ordered]@{
        appId = "gapseam-gfe"
        name = "Gapseam GFE"
        version = $version
        asset = "Gapseam.zip"
        downloadUrl = "http://github.samsungds.net/bh2-min/Gapseam/releases/download/$version/Gapseam.zip"
        sha256 = $sha256
        size = $size
        notes = $notes
        publishedAtUtc = $buildDate
        commit = $commit
        build_id = $buildId
    }
    Write-Utf8NoBom $manifestPath ($manifest | ConvertTo-Json -Depth 4)

    Write-Host "Company Release Manager work folder: $root"
    Write-Host "Build command: powershell -NoProfile -ExecutionPolicy Bypass -File .\build-company-release.ps1 -Clean"
    Write-Host "Company ZIP: $zipPath"
    Write-Host "Manifest: $manifestPath"
    Write-Host "Version: $version"
    Write-Host "Build ID: $buildId"
    Write-Host "Update channel: company"
    Write-Host "SHA-256: $sha256"
} finally {
    Write-Utf8NoBom $buildInfo $originalBuildInfo
    Remove-BuildInfoBytecode
    Remove-Item -LiteralPath $smokeFile -Force -ErrorAction SilentlyContinue
}
