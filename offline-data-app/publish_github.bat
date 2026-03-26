@echo off
REM ============================================================
REM Publish a GitHub Release with the installer attached.
REM
REM Prerequisites:
REM   1. GitHub CLI (gh) installed and authenticated
REM      Install: https://cli.github.com/
REM      Auth:    gh auth login
REM   2. Run build_installer.bat first (or use release.bat)
REM
REM Usage:
REM   publish_github.bat
REM   publish_github.bat "Fixed clustering bug, added dark mode"
REM
REM If no message is given, changelog is auto-generated from
REM git commits since the previous release tag.
REM ============================================================

setlocal EnableDelayedExpansion

REM --- Read version from version.json (written by bump_version.py) ---
set "VERSION="
for /f "tokens=2 delims=:, " %%a in ('findstr "\"version\"" version.json') do (
    if "!VERSION!"=="" (
        set "VERSION=%%~a"
        set "VERSION=!VERSION:"=!"
    )
)

if "!VERSION!"=="" (
    echo ERROR: Could not read version from version.json
    echo        Run: python bump_version.py patch
    exit /b 1
)

set "TAG=v!VERSION!"
set "INSTALLER=installer_output\SOCDataProcessor-Setup-!VERSION!.exe"

echo.
echo ============================================================
echo  Publish SOC Data Processor !TAG!
echo ============================================================
echo.

REM --- Check installer exists ---
if not exist "!INSTALLER!" (
    echo ERROR: Installer not found: !INSTALLER!
    echo        Run build_installer.bat first.
    exit /b 1
)

REM --- Check gh CLI ---
where gh >nul 2>&1
if errorlevel 1 (
    echo ERROR: GitHub CLI ^(gh^) not found.
    echo        Install from: https://cli.github.com/
    echo        Then run: gh auth login
    exit /b 1
)

REM --- Check git ---
where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: git not found in PATH.
    exit /b 1
)

REM --- Compute SHA256 ---
echo Computing SHA256...
set "SHA256="
for /f "skip=1 tokens=*" %%h in ('certutil -hashfile "!INSTALLER!" SHA256') do (
    if "!SHA256!"=="" set "SHA256=%%h"
)
echo   Hash: !SHA256!

REM --- Get file size ---
for %%f in ("!INSTALLER!") do set "FILESIZE=%%~zf"
echo   Size: !FILESIZE! bytes
echo.

REM --- Push git tag if not already pushed ---
echo Checking git tag !TAG!...
git tag "!TAG!" >nul 2>&1
if not errorlevel 1 (
    echo   Created local tag !TAG!
)
git push origin "!TAG!" >nul 2>&1
if errorlevel 1 (
    echo   WARNING: Could not push tag (may already exist on remote, continuing...)
) else (
    echo   Pushed tag !TAG! to remote.
)
echo.

REM --- Build changelog ---
set "NOTES=%~1"
set "BODY_FILE=%TEMP%\gh_release_body.md"

if "!NOTES!"=="" (
    REM Auto-generate from git log since previous tag
    echo Auto-generating changelog from git log...
    set "PREV_TAG="
    for /f %%t in ('git describe --tags --abbrev=0 "!TAG!^" 2^>nul') do set "PREV_TAG=%%t"

    if "!PREV_TAG!"=="" (
        REM No previous tag — use last 20 commits
        set "GIT_RANGE=HEAD"
        echo   No previous tag found, using recent commits.
    ) else (
        set "GIT_RANGE=!PREV_TAG!..!TAG!"
        echo   Changelog since !PREV_TAG!
    )

    (
        echo ## SOC Data Processor !TAG!
        echo.
        echo ### Changes
        echo.
        git log !GIT_RANGE! --pretty=format:"- %%s" --no-merges
        echo.
        echo.
        echo ### Installation
        echo.
        echo Download `SOCDataProcessor-Setup-!VERSION!.exe` below and run it.
        echo If you have a previous version, the installer upgrades automatically.
        echo.
        echo ### Verification
        echo.
        echo SHA256: `!SHA256!`
        echo Size: !FILESIZE! bytes
    ) > "!BODY_FILE!"
) else (
    REM Use the manually supplied message
    (
        echo ## SOC Data Processor !TAG!
        echo.
        echo !NOTES!
        echo.
        echo ### Installation
        echo.
        echo Download `SOCDataProcessor-Setup-!VERSION!.exe` below and run it.
        echo If you have a previous version, the installer upgrades automatically.
        echo.
        echo ### Verification
        echo.
        echo SHA256: `!SHA256!`
        echo Size: !FILESIZE! bytes
    ) > "!BODY_FILE!"
)

REM --- Check if release already exists ---
gh release view "!TAG!" >nul 2>&1
if not errorlevel 1 (
    echo WARNING: Release !TAG! already exists on GitHub.
    echo.
    set /p "OVERWRITE=Overwrite? (y/N): "
    if /i "!OVERWRITE!" neq "y" (
        echo Aborted.
        del "!BODY_FILE!" 2>nul
        exit /b 0
    )
    echo Deleting existing release...
    gh release delete "!TAG!" --yes
    git push origin --delete "!TAG!" 2>nul
    git tag -d "!TAG!" 2>nul
    git tag "!TAG!"
    git push origin "!TAG!"
)

REM --- Create the GitHub release ---
echo Creating GitHub release !TAG!...
gh release create "!TAG!" "!INSTALLER!" ^
    --title "SOC Data Processor !TAG!" ^
    --notes-file "!BODY_FILE!"

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
echo  Users will receive update notifications on next app launch.
echo ============================================================
