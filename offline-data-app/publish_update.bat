@echo off
REM ============================================================
REM Publish Update — copies installer + update.json to a folder
REM
REM Usage: publish_update.bat <destination_folder>
REM   e.g.: publish_update.bat \\server\shared\soc-updates
REM   e.g.: publish_update.bat C:\Updates\SOCDataProcessor
REM ============================================================

setlocal EnableDelayedExpansion

if "%~1"=="" (
    echo Usage: publish_update.bat ^<destination_folder^>
    echo.
    echo Example:
    echo   publish_update.bat \\server\shared\soc-updates
    echo   publish_update.bat C:\Updates\SOCDataProcessor
    exit /b 1
)

set "DEST=%~1"
set "VERSION="

REM Read version from version.json
for /f "tokens=2 delims=:," %%a in ('findstr "version" version.json') do (
    if "!VERSION!"=="" (
        set "VERSION=%%~a"
        set "VERSION=!VERSION: =!"
    )
)

set "INSTALLER=installer_output\SOCDataProcessor-Setup-!VERSION!.exe"

if not exist "!INSTALLER!" (
    echo ERROR: Installer not found: !INSTALLER!
    echo        Run build_installer.bat first.
    exit /b 1
)

echo ============================================================
echo  Publishing SOC Data Processor v!VERSION!
echo  To: %DEST%
echo ============================================================
echo.

REM Create destination if needed
if not exist "%DEST%" (
    mkdir "%DEST%"
    if errorlevel 1 (
        echo ERROR: Cannot create destination folder.
        exit /b 1
    )
)

REM Compute SHA256
echo Computing SHA256 hash...
for /f "skip=1 tokens=*" %%h in ('certutil -hashfile "!INSTALLER!" SHA256') do (
    if "!SHA256!"=="" set "SHA256=%%h"
)
echo   Hash: !SHA256!

REM Get file size
for %%f in ("!INSTALLER!") do set "FILESIZE=%%~zf"
echo   Size: !FILESIZE! bytes

REM Generate update.json
echo.
echo Generating update.json...
(
echo {
echo   "version": "!VERSION!",
echo   "build_date": "%date:~6,4%-%date:~3,2%-%date:~0,2%",
echo   "min_compatible_version": "1.0.0",
echo   "installer_filename": "SOCDataProcessor-Setup-!VERSION!.exe",
echo   "installer_size_bytes": !FILESIZE!,
echo   "sha256": "!SHA256!",
echo   "changelog": "- Update to version !VERSION!",
echo   "mandatory": false
echo }
) > "%DEST%\update.json"

REM Copy installer
echo Copying installer...
copy /y "!INSTALLER!" "%DEST%\" >nul
if errorlevel 1 (
    echo ERROR: Failed to copy installer.
    exit /b 1
)

echo.
echo ============================================================
echo  PUBLISHED SUCCESSFULLY
echo ============================================================
echo.
echo  Files in %DEST%:
echo    - update.json
echo    - SOCDataProcessor-Setup-!VERSION!.exe
echo.
echo  Tell users to set their update source to:
echo    %DEST%
echo.
echo  Or edit update.json to customize the changelog.
echo ============================================================
