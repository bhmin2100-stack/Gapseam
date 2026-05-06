@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion

rem ============================================================
rem 사용자가 수정할 값은 이 구역에만 모아두었습니다.
rem ============================================================
set "REPO_URL=https://github.com/사용자명/저장소명"
set "BRANCH=main"
set "TARGET_DIR=C:\원하는\폴더\경로"
rem ============================================================

set "BAT_FILE=%~f0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$p=$env:BAT_FILE;" ^
  "$marker='### POWERSHELL SCRIPT BELOW ###';" ^
  "$c=Get-Content -LiteralPath $p -Raw -Encoding UTF8;" ^
  "$i=$c.IndexOf($marker);" ^
  "if($i -lt 0){throw 'PowerShell 스크립트 구역을 찾지 못했습니다.'};" ^
  "$ps=$c.Substring($i + $marker.Length);" ^
  "Invoke-Expression $ps"

if errorlevel 1 goto FAIL

echo.
echo 동기화 완료
pause
exit /b 0

:FAIL
echo.
echo 오류가 발생했습니다. 위 메시지를 확인하세요.
pause
exit /b 1

### POWERSHELL SCRIPT BELOW ###
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$exitCode = 0
$tempRoot = $null

try {
    $repoUrl = ([string]$env:REPO_URL).Trim().TrimEnd('/')
    $branch = ([string]$env:BRANCH).Trim()
    $targetInput = ([string]$env:TARGET_DIR).Trim()

    if ([string]::IsNullOrWhiteSpace($repoUrl) -or $repoUrl -eq 'https://github.com/사용자명/저장소명') {
        throw 'REPO_URL을 실제 GitHub 저장소 주소로 수정하세요.'
    }
    if ([string]::IsNullOrWhiteSpace($branch)) {
        throw 'BRANCH 값을 입력하세요.'
    }
    if ([string]::IsNullOrWhiteSpace($targetInput) -or $targetInput -eq 'C:\원하는\폴더\경로') {
        throw 'TARGET_DIR을 실제 로컬 대상 폴더로 수정하세요.'
    }

    if ($repoUrl.ToLowerInvariant().EndsWith('.git')) {
        $repoUrl = $repoUrl.Substring(0, $repoUrl.Length - 4)
    }
    if ($repoUrl -notmatch '^https://github\.com/[^/]+/[^/]+$') {
        throw 'REPO_URL 형식은 https://github.com/사용자명/저장소명 이어야 합니다.'
    }

    $targetDir = [System.IO.Path]::GetFullPath($targetInput)
    $trimChars = [char[]]@('\', '/')
    $targetNormalized = $targetDir.TrimEnd($trimChars)
    $rootNormalized = ([System.IO.Path]::GetPathRoot($targetDir)).TrimEnd($trimChars)
    if ($targetNormalized -eq $rootNormalized) {
        throw '드라이브 루트 전체를 TARGET_DIR로 지정할 수 없습니다.'
    }

    $parentDir = Split-Path -LiteralPath $targetDir -Parent
    $targetName = Split-Path -LiteralPath $targetDir -Leaf
    if ([string]::IsNullOrWhiteSpace($parentDir) -or [string]::IsNullOrWhiteSpace($targetName)) {
        throw 'TARGET_DIR 경로를 확인하세요.'
    }
    if (-not (Test-Path -LiteralPath $parentDir)) {
        New-Item -ItemType Directory -Path $parentDir -Force | Out-Null
    }

    $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("github_zip_sync_{0}_{1}" -f $timestamp, [Guid]::NewGuid().ToString('N'))
    $zipPath = Join-Path $tempRoot 'repository.zip'
    $extractDir = Join-Path $tempRoot 'extract'

    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $extractDir -Force | Out-Null

    $branchForUrl = $branch -replace '\\', '/'
    $zipUrl = "$repoUrl/archive/refs/heads/$branchForUrl.zip"

    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    } catch {
        # Older Windows/PowerShell environments may already have a usable default.
    }

    Write-Host "GitHub ZIP 다운로드 중..."
    Write-Host "URL: $zipUrl"
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing

    Write-Host "ZIP 압축 해제 중..."
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

    $extractedRoots = @(Get-ChildItem -LiteralPath $extractDir -Directory)
    if ($extractedRoots.Count -ne 1) {
        throw 'ZIP 내부의 저장소 폴더를 하나로 특정하지 못했습니다.'
    }
    $newRepoDir = $extractedRoots[0].FullName

    $backupDir = $null
    if (Test-Path -LiteralPath $targetDir) {
        $backupDir = Join-Path $parentDir ("{0}.backup_{1}" -f $targetName, $timestamp)
        if (Test-Path -LiteralPath $backupDir) {
            throw "백업 폴더가 이미 존재합니다: $backupDir"
        }

        Write-Host "기존 로컬 폴더 백업 중..."
        Write-Host "백업 위치: $backupDir"
        Move-Item -LiteralPath $targetDir -Destination $backupDir
    }

    Write-Host "GitHub 기준 파일로 교체 중..."
    try {
        Move-Item -LiteralPath $newRepoDir -Destination $targetDir
    } catch {
        if ($backupDir -and (Test-Path -LiteralPath $backupDir) -and -not (Test-Path -LiteralPath $targetDir)) {
            Write-Host "교체 실패로 백업을 원래 위치로 복구합니다..."
            Move-Item -LiteralPath $backupDir -Destination $targetDir -ErrorAction SilentlyContinue
        }
        throw
    }

    Write-Host "대상 폴더: $targetDir"
    if ($backupDir) {
        Write-Host "백업 폴더: $backupDir"
    }
} catch {
    Write-Host ''
    Write-Host "오류: $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
} finally {
    if ($tempRoot -and (Test-Path -LiteralPath $tempRoot)) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

exit $exitCode
