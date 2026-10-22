@echo off
chcp 65001 >nul
echo Закройте Roblox полностью (и значок в трее), потом нажмите любую клавишу.
pause
taskkill /F /IM RobloxPlayerBeta.exe >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$d=Join-Path $env:LOCALAPPDATA 'Roblox'; $fs=Get-ChildItem $d -Filter 'GlobalBasicSettings*.xml' -ErrorAction SilentlyContinue; if(-not $fs){Write-Host 'Файл GlobalBasicSettings не найден в' $d; exit}; foreach($f in $fs){ $t=Get-Content $f.FullName -Raw; Write-Host '---' $f.FullName; [regex]::Matches($t,'<[^>]*VR[^>]*>[^<]*</[^>]*>') | ForEach-Object { Write-Host 'БЫЛО:' $_.Value }; $n=[regex]::Replace($t,'(<[^>]*name=\"VREnabled\"[^>]*>)\s*false\s*(</)','${1}true${2}'); if($n -ne $t){ [IO.File]::WriteAllText($f.FullName,$n,(New-Object Text.UTF8Encoding($false))); Write-Host 'VREnabled -> true' } else { Write-Host 'Менять нечего (уже true или поля нет)' } }"
echo.
echo Теперь запустите SteamVR и start_client.bat, потом откройте Roblox ЗАЛОГИНЕННЫМ и зайдите в любой плейс.
pause
