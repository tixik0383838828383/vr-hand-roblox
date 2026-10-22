@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "C:\VRHandDriver\layer" mkdir "C:\VRHandDriver\layer"
copy /y "%~dp0XrApiLayer_api_dump.dll" "C:\VRHandDriver\layer\" >nul
copy /y "%~dp0XrApiLayer_api_dump.json" "C:\VRHandDriver\layer\" >nul
reg add "HKCU\SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit" /v "C:\VRHandDriver\layer\XrApiLayer_api_dump.json" /t REG_DWORD /d 0 /f
echo.
echo Слой зарегистрирован для ВСЕХ OpenXR-программ (в том числе Roblox), переменные окружения не нужны.
echo Лог пишется в C:\VRHandDriver\xr_apidump.txt
echo.
echo Дальше: полностью закройте Roblox, запустите SteamVR и start_client.bat, зайдите в плейс с VR,
echo подождите минуту, закройте Roblox и пришлите C:\VRHandDriver\xr_apidump.txt
echo Когда закончите - запустите apidump_unregister.bat.
pause
