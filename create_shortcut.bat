@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "APP_DIR=%~dp0"
if "!APP_DIR:~-1!"=="\" set "APP_DIR=!APP_DIR:~0,-1!"

echo Creating desktop shortcut...

if not exist "!APP_DIR!\launch.bat" (
    echo ERROR: launch.bat not found in !APP_DIR!
    pause
    exit /b 1
)

if not exist "!APP_DIR!\Sprite_sheet_cutter_blank.ico" (
    echo ERROR: Icon file not found in !APP_DIR!
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$a='!APP_DIR!'; $l=$a+'\launch.bat'; $i=$a+'\Sprite_sheet_cutter_blank.ico'; $s=$env:USERPROFILE+'\Desktop\Gomba''s Sprite Sheet Cutter.lnk'; $w=New-Object -ComObject WScript.Shell; $c=$w.CreateShortcut($s); $c.TargetPath='cmd.exe'; $c.Arguments='/c '+[char]34+[char]34+$l+[char]34+[char]34; $c.WorkingDirectory=$a; $c.IconLocation=$i; $c.WindowStyle=1; $c.Description='Gomba''s Sprite Sheet Cutter'; $c.Save()"

if errorlevel 1 (
    echo ERROR: Failed to create desktop shortcut.
    pause
    exit /b 1
)

echo [OK] Shortcut created: %USERPROFILE%\Desktop\Gomba's Sprite Sheet Cutter.lnk
echo.
pause
