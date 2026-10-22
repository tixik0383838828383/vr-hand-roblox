$ErrorActionPreference = "Continue"
$out = "C:\VRHandDriver\report.txt"
New-Item -ItemType Directory -Path "C:\VRHandDriver" -Force | Out-Null
function W($t) { Add-Content -Path $out -Value $t -Encoding UTF8 }
Remove-Item $out -ErrorAction SilentlyContinue
W "=== Отчёт $(Get-Date) ==="

W "`n--- Реестр: слои OpenXR ---"
foreach ($k in "HKCU:\SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit","HKLM:\SOFTWARE\Khronos\OpenXR\1\ApiLayers\Implicit") {
  W $k; try { (Get-ItemProperty $k -ErrorAction Stop).PSObject.Properties | Where-Object { $_.Name -notlike "PS*" } | ForEach-Object { W ("  {0} = {1}" -f $_.Name,$_.Value) } } catch { W "  (нет)" }
}
W "`n--- Реестр: активный OpenXR runtime ---"
foreach ($k in "HKLM:\SOFTWARE\Khronos\OpenXR\1","HKLM:\SOFTWARE\WOW6432Node\Khronos\OpenXR\1","HKCU:\SOFTWARE\Khronos\OpenXR\1") {
  try { W ("{0}: {1}" -f $k,(Get-ItemProperty $k -ErrorAction Stop).ActiveRuntime) } catch { W "$k : (нет)" }
}

W "`n--- Тест слоя через реестр (hello_xr без переменных окружения) ---"
Remove-Item "C:\VRHandDriver\xr_apidump.txt" -ErrorAction SilentlyContinue
$hx = Join-Path $PSScriptRoot "hello_xr.exe"
if (Test-Path $hx) {
  $p = Start-Process -FilePath $hx -ArgumentList "-g","D3D11" -PassThru -WindowStyle Hidden
  Start-Sleep -Seconds 6
  if (-not $p.HasExited) { $p.Kill() }
  if (Test-Path "C:\VRHandDriver\xr_apidump.txt") { W ("слой через реестр РАБОТАЕТ, файл {0} байт" -f (Get-Item "C:\VRHandDriver\xr_apidump.txt").Length) } else { W "слой через реестр НЕ работает (файла нет)" }
} else { W "hello_xr.exe не найден рядом со скриптом" }

W "`n--- Файл настроек Roblox ---"
$rb = Join-Path $env:LOCALAPPDATA "Roblox"
W "Папка: $rb"
try { Get-ChildItem $rb -ErrorAction Stop | ForEach-Object { W ("  {0}  {1}" -f $_.Name,$_.LastWriteTime) } } catch { W "  (папки нет)" }
Get-ChildItem $rb -Filter "GlobalBasicSettings*.xml" -ErrorAction SilentlyContinue | ForEach-Object {
  W "--- $($_.FullName) $($_.LastWriteTime)"
  Select-String -Path $_.FullName -Pattern "VR|Vr" | ForEach-Object { W ("  " + $_.Line.Trim()) }
}

W "`n--- Где установлен RobloxPlayerBeta.exe ---"
$cands = @("$env:LOCALAPPDATA\Roblox","${env:ProgramFiles(x86)}\Roblox","$env:ProgramFiles\Roblox","$env:ProgramFiles\WindowsApps")
foreach ($c in $cands) { if (Test-Path $c) { Get-ChildItem $c -Recurse -Filter "RobloxPlayerBeta.exe" -ErrorAction SilentlyContinue | ForEach-Object { W $_.FullName } } }
W "--- Запущенные процессы Roblox"
Get-Process | Where-Object { $_.ProcessName -like "*Roblox*" } | ForEach-Object { W ("  {0} {1}" -f $_.ProcessName,$_.Path) }

W "`n--- Последний лог Roblox: строки про VR/XR ---"
$logDir = Join-Path $rb "logs"
$log = Get-ChildItem $logDir -Filter "*Player*last.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($log) {
  W "$($log.FullName) $($log.LastWriteTime)"
  Select-String -Path $log.FullName -Pattern "VR|OpenXR|XR " -CaseSensitive:$false | Select-Object -First 80 | ForEach-Object { W ("  " + $_.Line.Substring(0,[Math]::Min(300,$_.Line.Length))) }
} else { W "  (логов нет в $logDir)" }
Write-Host "Готово. Файл: $out"
