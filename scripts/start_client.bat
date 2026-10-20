@echo off
chcp 65001 >nul
cd /d "%~dp0client"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 vrhand.py %*
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python vrhand.py %*
    ) else (
        echo Python не найден. Установите Python 3.8+ с https://www.python.org/downloads/
        echo и поставьте галочку "Add python.exe to PATH" в установщике.
    )
)
echo.
pause
