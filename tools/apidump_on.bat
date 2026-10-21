@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Включаю запись вызовов OpenXR (слой api_dump) для всех программ.
setx XR_API_LAYER_PATH "%~dp0" >nul
setx XR_ENABLE_API_LAYERS "XR_APILAYER_LUNARG_api_dump" >nul
setx XR_API_DUMP_EXPORT_TYPE "text" >nul
setx XR_API_DUMP_FILE_NAME "C:\VRHandDriver\xr_apidump.txt" >nul
echo.
echo Готово. Теперь:
echo  1. Полностью закройте Roblox (в том числе значок в трее - правый клик - Выход).
echo  2. Запустите SteamVR и start_client.bat.
echo  3. Зайдите в плейс Roblox с включенным VR, подождите минуту, закройте Roblox.
echo  4. Пришлите файл C:\VRHandDriver\xr_apidump.txt
echo  5. Потом запустите apidump_off.bat
pause
