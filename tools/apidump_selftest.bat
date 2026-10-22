@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "C:\VRHandDriver" mkdir "C:\VRHandDriver"
if not exist "C:\VRHandDriver\layer" mkdir "C:\VRHandDriver\layer"
copy /y "%~dp0XrApiLayer_api_dump.dll" "C:\VRHandDriver\layer\" >nul
copy /y "%~dp0XrApiLayer_api_dump.json" "C:\VRHandDriver\layer\" >nul
del "C:\VRHandDriver\xr_apidump_selftest.txt" >nul 2>&1
set "XR_API_LAYER_PATH=C:\VRHandDriver\layer"
set "XR_ENABLE_API_LAYERS=XR_APILAYER_LUNARG_api_dump"
set "XR_API_DUMP_EXPORT_TYPE=text"
set "XR_API_DUMP_FILE_NAME=C:\VRHandDriver\xr_apidump_selftest.txt"

echo ТЕСТ 1: проверка самого слоя на тестовой программе hello_xr.
echo SteamVR и start_client.bat должны быть запущены.
pause
set "XR_LOADER_DEBUG=all"
set "LOG=C:\VRHandDriver\selftest_log.txt"
echo Папка: %~dp0 > "%LOG%"
dir /b "%~dp0" >> "%LOG%" 2>&1
type "%~dp0XrApiLayer_api_dump.json" >> "%LOG%" 2>&1
hello_xr.exe -g D3D11 -ff Hmd -vc Stereo -bm Opaque < nul >> "%LOG%" 2>&1
timeout /t 1 >nul
if exist "C:\VRHandDriver\xr_apidump_selftest.txt" (
  for %%F in ("C:\VRHandDriver\xr_apidump_selftest.txt") do echo Слой РАБОТАЕТ, файл создан, размер %%~zF байт
) else (
  echo Слой НЕ работает даже с hello_xr
)

echo.
echo ТЕСТ 2: ищу библиотеки OpenXR в папке Roblox...
set "OUT=C:\VRHandDriver\roblox_files.txt"
echo Roblox openxr files: > "%OUT%"
dir /s /b "%LOCALAPPDATA%\Roblox\Versions\openxr*.dll" >> "%OUT%" 2>&1
dir /s /b "%LOCALAPPDATA%\Roblox\Versions\*xr*.dll" >> "%OUT%" 2>&1
dir /b "%LOCALAPPDATA%\Roblox\Versions" >> "%OUT%" 2>&1
type "%OUT%"
echo.
echo Пришлите мне файл C:\VRHandDriver\selftest_log.txt и текст выше (скриншот или копию) и файл %OUT%
pause
