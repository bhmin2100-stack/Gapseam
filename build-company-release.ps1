[CmdletBinding()]
param([switch]$Clean)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSCommandPath
Set-Location $root

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

try {
@"
from __future__ import annotations

APP_VERSION = "$version"
BUILD_COMMIT = "$commit"
BUILD_ID = "$buildId"
BUILD_DATE = "$buildDate"
UPDATE_CHANNEL = "company"
"@ | Set-Content -LiteralPath $buildInfo -Encoding utf8

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
        downloadUrl = "https://github.samsungds.net/bh2-min/Gapseam/releases/download/$version/Gapseam.zip"
        sha256 = $sha256
        size = $size
        notes = $notes
        publishedAtUtc = $buildDate
        commit = $commit
        build_id = $buildId
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding utf8

    Write-Host "Company Release Manager work folder: $root"
    Write-Host "Build command: powershell -NoProfile -ExecutionPolicy Bypass -File .\build-company-release.ps1 -Clean"
    Write-Host "Company ZIP: $zipPath"
    Write-Host "Manifest: $manifestPath"
    Write-Host "Version: $version"
    Write-Host "SHA-256: $sha256"
} finally {
    $originalBuildInfo | Set-Content -LiteralPath $buildInfo -Encoding utf8
}
