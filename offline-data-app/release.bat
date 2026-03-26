@echo off
REM ============================================================
REM Full release pipeline: bump version → build → publish
REM
REM Usage:
REM   release.bat patch
REM   release.bat minor
REM   release.bat major
REM   release.bat 1.2.3
REM   release.bat patch "Fixed clustering bug, improved dashboard"
REM
REM What this does:
REM   1. Bumps version in version.py + version.json (via bump_version.py)
REM   2. Git-commits the bump and creates a version tag
REM   3. Pushes commit + tag to remote
REM   4. Builds PyInstaller bundle + Inno Setup installer
REM   5. Publishes the installer to GitHub Releases
REM      (changelog auto-generated from git log since previous tag)
REM ============================================================

setlocal EnableDelayedExpansion

REM --- Validate arguments ---
set "BUMP_TYPE=%~1"
set "CHANGELOG=%~2"

if "!BUMP_TYPE!"=="" (
    echo Usage: release.bat ^<patch^|minor^|major^|X.Y.Z^> [^"changelog message^"]
    echo.
    echo Examples:
    echo   release.bat patch
    echo   release.bat minor "Added search tab and clustering improvements"
    echo   release.bat 1.2.0
    exit /b 1
)

echo.
echo ============================================================
echo  SOC Data Processor - Full Release Pipeline
echo ============================================================
echo  Bump type : !BUMP_TYPE!
if not "!CHANGELOG!"=="" (
    echo  Changelog : !CHANGELOG!
)
echo ============================================================
echo.

REM --- Check prerequisites ---
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: python not found in PATH.
    exit /b 1
)
where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: git not found in PATH.
    exit /b 1
)
where gh >nul 2>&1
if errorlevel 1 (
    echo ERROR: GitHub CLI ^(gh^) not found.
    echo        Install: https://cli.github.com/ then run: gh auth login
    exit /b 1
)

REM --- Check working directory is clean ---
git diff --quiet --exit-code >nul 2>&1
if errorlevel 1 (
    echo WARNING: You have unstaged changes.
    echo.
    git status --short
    echo.
    set /p "CONT=Continue anyway? (y/N): "
    if /i "!CONT!" neq "y" (
        echo Aborted. Commit or stash your changes first.
        exit /b 1
    )
)

REM ==========================================================
REM STEP 1: Bump version
REM ==========================================================
echo [1/4] Bumping version (!BUMP_TYPE!)...
python bump_version.py "!BUMP_TYPE!" --commit
if errorlevel 1 (
    echo ERROR: Version bump failed.
    exit /b 1
)
echo.

REM --- Read the new version ---
set "VERSION="
for /f "tokens=2 delims=:, " %%a in ('findstr "\"version\"" version.json') do (
    if "!VERSION!"=="" (
        set "VERSION=%%~a"
        set "VERSION=!VERSION:"=!"
    )
)
echo  New version: !VERSION!
echo.

REM ==========================================================
REM STEP 2: Push commit + tag
REM ==========================================================
echo [2/4] Pushing commit and tag v!VERSION! to remote...
git push
if errorlevel 1 (
    echo ERROR: git push failed.
    exit /b 1
)
git push origin "v!VERSION!"
if errorlevel 1 (
    echo ERROR: Failed to push tag v!VERSION!.
    exit /b 1
)
echo   Pushed.
echo.

REM ==========================================================
REM STEP 3: Build installer
REM ==========================================================
echo [3/4] Building installer...
call build_installer.bat
if errorlevel 1 (
    echo ERROR: Build failed.
    exit /b 1
)
echo.

REM ==========================================================
REM STEP 4: Publish to GitHub
REM ==========================================================
echo [4/4] Publishing to GitHub Releases...
if "!CHANGELOG!"=="" (
    call publish_github.bat
) else (
    call publish_github.bat "!CHANGELOG!"
)
if errorlevel 1 (
    echo ERROR: Publish failed.
    exit /b 1
)

echo.
echo ============================================================
echo  RELEASE COMPLETE: v!VERSION!
echo ============================================================
echo.
echo  Users will see the update notification on next app launch.
echo ============================================================
