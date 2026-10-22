@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0collect_report.ps1"
echo.
echo Пришлите мне файл C:\VRHandDriver\report.txt
pause
