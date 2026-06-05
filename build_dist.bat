@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "DIST_NAME=Gombas Sprite Sheet Cutter"
set "ZIP_FILE=%~dp0!DIST_NAME!.zip"
set "STAGE_DIR=%TEMP%\sprite_cutter_dist"

echo ============================================================
echo   Building distribution: "!DIST_NAME!.zip"
echo ============================================================
echo.

:: ── Remove old zip ────────────────────────────────────────────────────────────
if exist "!ZIP_FILE!" (
    echo Removing old zip...
    del /f /q "!ZIP_FILE!"
)

:: ── Create staging folder with named subfolder ───────────────────────────────
if exist "!STAGE_DIR!" rd /s /q "!STAGE_DIR!"
mkdir "!STAGE_DIR!\!DIST_NAME!"
if errorlevel 1 (
    echo ERROR: Could not create staging directory.
    pause
    exit /b 1
)

:: ── Copy files explicitly (no wildcards) ────────────────────────────────────
echo Staging files...
for %%F in (
    launch.bat
    create_shortcut.bat
    app.py
    sprite_cutter.py
    sprite_detector.py
    bg_remover.py
    requirements.txt
    Sprite_sheet_cutter_blank.ico
    logo.png
    README.md
    README.html
) do (
    if exist "%%F" (
        copy /y "%%F" "!STAGE_DIR!\!DIST_NAME!\%%F" >nul
        echo   + %%F
    ) else (
        echo   SKIPPED ^(not found^): %%F
    )
)
echo.

:: ── Compress with PowerShell ──────────────────────────────────────────────────
:: Pass paths via env vars — avoids apostrophe in "Gomba's" breaking PS string literals
echo Compressing...
set "SPRITE_STAGE_DIR=!STAGE_DIR!"
set "SPRITE_ZIP_FILE=!ZIP_FILE!"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path ($env:SPRITE_STAGE_DIR + '\*') -DestinationPath $env:SPRITE_ZIP_FILE -Force"

if errorlevel 1 (
    echo ERROR: Compression failed.
    rd /s /q "!STAGE_DIR!"
    pause
    exit /b 1
)

:: ── Cleanup ───────────────────────────────────────────────────────────────────
rd /s /q "!STAGE_DIR!"

echo.
echo ============================================================
echo   Done!
echo   Output: !ZIP_FILE!
echo ============================================================
echo.
pause
