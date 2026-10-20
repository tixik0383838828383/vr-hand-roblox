# Установка драйвера VRHand в SteamVR.
# Запускать через install.bat (двойной клик). SteamVR при этом должен быть закрыт.
#
# Что делает скрипт:
#   1. находит SteamVR;
#   2. регистрирует папку vrhand\ как драйвер (vrpathreg adddriver) — файлы в Program Files не копируются;
#   3. правит steamvr.vrsettings: использовать только наш драйвер и не запускать SteamVR Home.
#      Старый файл настроек сохраняется как steamvr.vrsettings.vrhand-backup.

param(
    [string]$SteamVRPath = ""
)

$ErrorActionPreference = "Stop"

function Fail($msg) {
    Write-Host ""
    Write-Host "ОШИБКА: $msg" -ForegroundColor Red
    exit 1
}

$root = Split-Path $PSScriptRoot -Parent
$driverDir = Join-Path $root "vrhand"
$dll = Join-Path $driverDir "bin\win64\driver_vrhand.dll"

if (-not (Test-Path $dll)) {
    Fail "Не найден $dll`nСкачайте готовый архив VRHand.zip со страницы Releases и запускайте install.bat из распакованной папки."
}

# --- 1. Ищем Steam и SteamVR -------------------------------------------------
$steamRoot = $null
foreach ($key in @("HKCU:\Software\Valve\Steam", "HKLM:\SOFTWARE\WOW6432Node\Valve\Steam")) {
    try {
        $p = (Get-ItemProperty -Path $key -ErrorAction Stop)
        $candidate = if ($p.SteamPath) { $p.SteamPath } else { $p.InstallPath }
        if ($candidate -and (Test-Path $candidate)) { $steamRoot = $candidate -replace "/", "\"; break }
    } catch { }
}
if (-not $steamRoot -and (Test-Path "C:\Program Files (x86)\Steam")) { $steamRoot = "C:\Program Files (x86)\Steam" }

if (-not $SteamVRPath) {
    $libraries = @()
    if ($steamRoot) {
        $libraries += $steamRoot
        $vdf = Join-Path $steamRoot "steamapps\libraryfolders.vdf"
        if (Test-Path $vdf) {
            foreach ($m in [regex]::Matches((Get-Content $vdf -Raw), '"path"\s+"([^"]+)"')) {
                $libraries += ($m.Groups[1].Value -replace "\\\\", "\")
            }
        }
    }
    foreach ($lib in ($libraries | Select-Object -Unique)) {
        $candidate = Join-Path $lib "steamapps\common\SteamVR"
        if (Test-Path (Join-Path $candidate "bin\win64\vrpathreg.exe")) { $SteamVRPath = $candidate; break }
    }
}

if (-not $SteamVRPath -or -not (Test-Path (Join-Path $SteamVRPath "bin\win64\vrpathreg.exe"))) {
    Fail ("SteamVR не найден.`n" +
          "1) Установите Steam: https://store.steampowered.com/about/`n" +
          "2) В Steam: Библиотека -> в фильтре выберите 'Инструменты' -> SteamVR -> Установить (бесплатно).`n" +
          "3) Запустите install.bat ещё раз.`n" +
          "Если SteamVR стоит в нестандартном месте: powershell -File scripts\install.ps1 -SteamVRPath `"D:\...\SteamVR`"")
}
Write-Host "SteamVR: $SteamVRPath"

# --- 2. SteamVR должен быть закрыт ------------------------------------------------
$running = Get-Process -Name vrserver, vrmonitor, vrcompositor, vrdashboard, vrstartup -ErrorAction SilentlyContinue
if ($running) {
    Fail "SteamVR сейчас запущен. Закройте его (правый клик на значок SteamVR в трее -> Выход) и запустите install.bat снова."
}

# --- 3. Регистрируем драйвер -------------------------------------------------------
$vrpathreg = Join-Path $SteamVRPath "bin\win64\vrpathreg.exe"
# Если драйвер уже был зарегистрирован — снимаем, чтобы не было дублей (ошибки здесь не важны).
try { & $vrpathreg removedriver $driverDir 2>&1 | Out-Null } catch { }
& $vrpathreg adddriver $driverDir
if ($LASTEXITCODE -ne 0) { Fail "vrpathreg adddriver завершился с кодом $LASTEXITCODE" }
Write-Host "Драйвер зарегистрирован: $driverDir" -ForegroundColor Green

# --- 4. Настройки SteamVR ----------------------------------------------------------
$settingsPath = $null
if ($steamRoot) { $settingsPath = Join-Path $steamRoot "config\steamvr.vrsettings" }

function Show-ManualSettings {
    Write-Host ""
    Write-Host "Добавьте вручную в файл steamvr.vrsettings (папка Steam\config) в раздел ""steamvr"":" -ForegroundColor Yellow
    Write-Host '    "forcedDriver": "vrhand",'
    Write-Host '    "activateMultipleDrivers": true,'
    Write-Host '    "enableHomeApp": false'
}

if ($settingsPath -and (Test-Path (Split-Path $settingsPath))) {
    try {
        if (Test-Path $settingsPath) {
            $backup = "$settingsPath.vrhand-backup"
            if (-not (Test-Path $backup)) { Copy-Item $settingsPath $backup }
            $json = Get-Content $settingsPath -Raw | ConvertFrom-Json
        } else {
            $json = [pscustomobject]@{}
        }
        if (-not $json.PSObject.Properties["steamvr"]) {
            $json | Add-Member -NotePropertyName "steamvr" -NotePropertyValue ([pscustomobject]@{})
        }
        $sv = $json.steamvr
        $sv | Add-Member -NotePropertyName "forcedDriver" -NotePropertyValue "vrhand" -Force
        $sv | Add-Member -NotePropertyName "activateMultipleDrivers" -NotePropertyValue $true -Force
        $sv | Add-Member -NotePropertyName "enableHomeApp" -NotePropertyValue $false -Force
        $text = $json | ConvertTo-Json -Depth 30
        # SteamVR не любит BOM в начале файла, поэтому пишем UTF-8 без BOM.
        [System.IO.File]::WriteAllText($settingsPath, $text, (New-Object System.Text.UTF8Encoding($false)))
        Write-Host "Настройки SteamVR обновлены: $settingsPath" -ForegroundColor Green
    } catch {
        Write-Host "Не удалось изменить steamvr.vrsettings автоматически: $($_.Exception.Message)" -ForegroundColor Yellow
        Show-ManualSettings
    }
} else {
    Write-Host "Папка Steam\config не найдена." -ForegroundColor Yellow
    Show-ManualSettings
}

Write-Host ""
Write-Host "Готово. Дальше:" -ForegroundColor Cyan
Write-Host "  1. Запустите SteamVR. Должен появиться виртуальный шлем и два контроллера (зелёные значки)."
Write-Host "  2. Запустите start_client.bat (окно управления)."
Write-Host "  3. В SteamVR: Настройки -> Разработчик -> Set SteamVR as OpenXR runtime."
Write-Host "  4. Запустите Roblox-плейс. Подробности — в README.md."
Write-Host ""
Write-Host "Не перемещайте и не удаляйте эту папку, пока драйвер установлен." -ForegroundColor Yellow
