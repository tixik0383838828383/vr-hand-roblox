@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "C:\VRHandDriver" mkdir "C:\VRHandDriver"
if not exist "C:\VRHandDriver\layer" mkdir "C:\VRHandDriver\layer"
copy /y "%~dp0XrApiLayer_api_dump.dll" "C:\VRHandDriver\layer\" >nul
copy /y "%~dp0XrApiLayer_api_dump.json" "C:\VRHandDriver\layer\" >nul
del "C:\VRHandDriver\xr_apidump.txt" >nul 2>&1

rem Переменные действуют только для этого окна и запущенного из него Roblox.
set "XR_API_LAYER_PATH=C:\VRHandDriver\layer"
set "XR_ENABLE_API_LAYERS=XR_APILAYER_LUNARG_api_dump"
set "XR_API_DUMP_EXPORT_TYPE=text"
set "XR_API_DUMP_FILE_NAME=C:\VRHandDriver\xr_apidump.txt"

echo Закрываю Roblox, если он запущен...
taskkill /F /IM RobloxPlayerBeta.exe >nul 2>&1
taskkill /F /IM RobloxPlayerLauncher.exe >nul 2>&1
timeout /t 2 >nul

echo.
echo ПЕРЕД продолжением: SteamVR должен быть запущен (зелёные значки) и start_client.bat тоже.
pause

echo Запускаю Roblox из этого окна...
start "" "roblox-player:1"
echo.
echo 1. В открывшемся Roblox зайдите в плейс с включённым VR.
echo 2. Подождите минуту и ПОЛНОСТЬЮ закройте Roblox (и значок в трее).
echo 3. Вернитесь в это окно и нажмите любую клавишу.
pause

echo.
if exist "C:\VRHandDriver\xr_apidump.txt" (
  for %%F in ("C:\VRHandDriver\xr_apidump.txt") do echo ФАЙЛ СОЗДАН, размер %%~zF байт: %%F
) else (
  echo Файл НЕ создан - Roblox не загрузил слой OpenXR. Так и напишите мне.
)
pause
