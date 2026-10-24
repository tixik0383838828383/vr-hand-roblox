@echo off
chcp 65001 >nul
cd /d "%~dp0"
:menu
echo.
echo ==== VR в Roblox: где включать ====
echo  1 - выключить VR в Studio (в Player VR включается в игре)  [для игры]
echo  2 - VR везде выключить
echo  3 - VR включить в Studio                             [для тестов своих игр]
echo  4 - показать текущее состояние
echo  5 - вернуть обычные настройки Roblox Player (убрать файл, созданный раньше)
echo  0 - выход
echo Перед пунктами 1-3 полностью закройте Roblox и Studio (и значок в трее).
choice /c 123450 /n /m "Ваш выбор: "
if errorlevel 6 goto :eof
if errorlevel 5 powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\roblox_vr.ps1" -Action ResetPlayer & goto menu
if errorlevel 4 powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\roblox_vr.ps1" -Action Status & goto menu
if errorlevel 3 powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\roblox_vr.ps1" -Action StudioOn & goto menu
if errorlevel 2 powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\roblox_vr.ps1" -Action AllOff & goto menu
if errorlevel 1 powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\roblox_vr.ps1" -Action PlayerOnly & goto menu
goto menu
