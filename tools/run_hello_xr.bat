@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Запускаю hello_xr. SteamVR и start_client.bat должны быть уже запущены.
echo Результат сохраняется в hello_xr_log.txt рядом с этим файлом.
echo.
set XR_LOADER_DEBUG=all
hello_xr.exe -g D3D11 -ff Hmd -vc Stereo -bm Opaque > hello_xr_log.txt 2>&1
echo Код выхода: %errorlevel% >> hello_xr_log.txt
echo Готово. Пришлите файл hello_xr_log.txt.
pause
