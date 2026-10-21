@echo off
chcp 65001 >nul
echo Выключаю запись вызовов OpenXR.
reg delete "HKCU\Environment" /v XR_API_LAYER_PATH /f >nul 2>&1
reg delete "HKCU\Environment" /v XR_ENABLE_API_LAYERS /f >nul 2>&1
reg delete "HKCU\Environment" /v XR_API_DUMP_EXPORT_TYPE /f >nul 2>&1
reg delete "HKCU\Environment" /v XR_API_DUMP_FILE_NAME /f >nul 2>&1
echo Готово. Перезапустите Roblox.
pause
