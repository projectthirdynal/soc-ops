@echo off
REM ============================================================
REM Publish a GitHub Release with the installer attached
REM
REM Prerequisites:
REM   1. GitHub CLI (gh) installed and authenticated
REM      Install: https://cli.github.com/
REM      Auth:    gh auth login
REM   2. Run build_installer.bat first
REM
REM Usage:
REM   publish_github.bat
REM   publish_github.bat "Fixed clustering bug, added PDF export"
REM ============================================================

setlocal EnableDelayedExpansion

REM --- Read version from version.json ---
set "VERSION="
for /f "tokens=2 delims=:," %%a in ('findstr "version" version.json') do (
    if "!VERSION!"=="" (
        set "VERSION=%%~a"
        set "VERSION=!VERSION: =!"
    )
)

if "!VERSION!"=="" (
    echo ERROR: Could not read version from version.json
    exit /b 1
)

set "TAG=v!VERSION!"
set "INSTALLER=installer_output\SOCDataProcessor-Setup-!VERSION!.exe"

if not exist "!INSTALLER!" (
    echo ERROR: Installer not found: !INSTALLER!
    echo        Run build_installer.bat first.
    exit /b 1
)

REM --- Check gh CLI is available ---
where gh >nul 2>&1
if errorlevel 1 (
    echo ERROR: GitHub CLI ^(gh^) not found.
    echo        Install from: https://cli.github.com/
    echo        Then run: gh auth login
    exit /b 1
)

REM --- Compute SHA256 ---
echo Computing SHA256 hash...
set "SHA256="
for /f "skip=1 tokens=*" %%h in ('certutil -hashfile "!INSTALLER!" SHA256') do (
    if "!SHA256!"=="" set "SHA256=%%h"
)
echo   Hash: !SHA256!

REM --- Get file size ---
for %%f in ("!INSTALLER!") do set "FILESIZE=%%~zf"
echo   Size: !FILESIZE! bytes

REM --- Build release notes ---
set "NOTES=%~1"
if "!NOTES!"=="" set "NOTES=Release !TAG!"

REM Create temp file for release body
set "BODY_FILE=%TEMP%\gh_release_body.md"
(
echo ## SOC Data Processor !TAG!
echo.
echo !NOTES!
echo.
echo ### Installation
echo.
echo Download `SOCDataProcessor-Setup-!VERSION!.exe` below and run it.
echo If you have a previous version installed, the installer will upgrade it automatically.
echo.
echo ### Verification
echo.
echo SHA256: `!SHA256!`
echo.
echo ---
echo *Installer size: !FILESIZE! bytes*
) > "!BODY_FILE!"

echo.
echo ============================================================
echo  Publishing SOC Data Processor !TAG! to GitHub
echo ============================================================
echo.

REM --- Check if release already exists ---
gh release view "!TAG!" >nul 2>&1
if not errorlevel 1 (
    echo WARNING: Release !TAG! already exists.
    echo.
    set /p "OVERWRITE=Overwrite existing release? (y/N): "
    if /i "!OVERWRITE!" neq "y" (
        echo Aborted.
        del "!BODY_FILE!" 2>nul
        exit /b 0
    )
    echo Deleting existing release...
    gh release delete "!TAG!" --yes
    git push origin --delete "!TAG!" 2>nul
)

REM --- Create the release ---
echo Creating GitHub release !TAG!...
gh release create "!TAG!" "!INSTALLER!" --title "SOC Data Processor !TAG!" --notes-file "!BODY_FILE!"

if errorlevel 1 (
    echo ERROR: Failed to create GitHub release.
    del "!BODY_FILE!" 2>nul
    exit /b 1
)

del "!BODY_FILE!" 2>nul

echo.
echo ============================================================
echo  PUBLISHED SUCCESSFULLY
echo ============================================================
echo.
echo  Release: !TAG!
echo  Asset:   SOCDataProcessor-Setup-!VERSION!.exe
echo  SHA256:  !SHA256!
echo.
echo  Users will receive update notifications automatically.
echo  View at: https://github.com/projectthirdynal/soc-ops/releases/tag/!TAG!
echo ============================================================
