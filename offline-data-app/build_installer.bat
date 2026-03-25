@echo off
REM ============================================================
REM Full build pipeline: PyInstaller + Inno Setup
REM Run this on your Windows build machine.
REM
REM Prerequisites:
REM   1. Python 3.10+ with venv
REM   2. Inno Setup 6.x installed (iscc.exe in PATH or default location)
REM ============================================================

setlocal EnableDelayedExpansion

REM --- Read version ---
set "VERSION="
for /f "tokens=2 delims=:," %%a in ('findstr "version" version.json') do (
    if "!VERSION!"=="" (
        set "VERSION=%%~a"
        set "VERSION=!VERSION: =!"
    )
)

echo ============================================================
echo  SOC Data Processor v!VERSION! - Full Build Pipeline
echo ============================================================
echo.

REM --- Step 1: Set up venv and install deps ---
echo [1/4] Setting up Python environment...
if not exist ".venv" (
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        exit /b 1
    )
)
call .venv\Scripts\activate.bat

pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    exit /b 1
)
echo       Done.
echo.

REM --- Step 2: Run PyInstaller ---
echo [2/4] Building with PyInstaller...
if exist "dist\OfflineDataApp" (
    echo       Cleaning previous build...
    rmdir /s /q dist\OfflineDataApp
)
pyinstaller app.spec --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    exit /b 1
)
echo       Done. Output: dist\OfflineDataApp\
echo.

REM --- Step 3: Find Inno Setup ---
echo [3/4] Looking for Inno Setup compiler...
set "ISCC="
where iscc >nul 2>&1
if not errorlevel 1 (
    set "ISCC=iscc"
) else (
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
        set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    ) else if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
        set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
    )
)

if "!ISCC!"=="" (
    echo WARNING: Inno Setup not found. Skipping installer creation.
    echo          Install from: https://jrsoftware.org/isdl.php
    echo          The PyInstaller output in dist\OfflineDataApp\ is still usable.
    exit /b 0
)
echo       Found: !ISCC!
echo.

REM --- Step 4: Build installer ---
echo [4/4] Building Windows installer...
if not exist "installer_output" mkdir installer_output

REM Generate version.iss so Inno Setup reads the version automatically
echo #define MyAppVersion "!VERSION!" > version.iss
echo       Generated version.iss with version !VERSION!

"!ISCC!" installer.iss
if errorlevel 1 (
    echo ERROR: Inno Setup compilation failed.
    exit /b 1
)
echo.
echo ============================================================
echo  BUILD COMPLETE
echo ============================================================
echo.
echo  Installer: installer_output\SOCDataProcessor-Setup-!VERSION!.exe
echo.
echo  To publish this update to users:
echo    publish_github.bat "Description of changes"
echo.
echo  This uploads the installer to GitHub Releases.
echo  Users will be notified automatically when they open the app.
echo.
echo  For the NEXT release, remember to:
echo    1. Update version in app\core\version.py and version.json
echo    2. Update MyAppVersion in installer.iss
echo    3. Re-run this script
echo.
echo ============================================================
