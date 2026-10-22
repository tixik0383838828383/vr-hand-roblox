@echo off
chcp 65001 >nul
reg delete "HKCU\SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit" /v "C:\VRHandDriver\layer\XrApiLayer_api_dump.json" /f
echo Слой удалён из регистрации.
pause
