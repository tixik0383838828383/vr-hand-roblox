# Удаление драйвера VRHand из SteamVR. Запускать через uninstall.bat. SteamVR должен быть закрыт.
param([string]$SteamVRPath = "")

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$driverDir = Join-Path $root "vrhand"

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

if (Get-Process -Name vrserver, vrmonitor, vrcompositor -ErrorAction SilentlyContinue) {
    Write-Host "ОШИБКА: закройте SteamVR и запустите uninstall.bat снова." -ForegroundColor Red
    exit 1
}

if ($SteamVRPath -and (Test-Path (Join-Path $SteamVRPath "bin\win64\vrpathreg.exe"))) {
    & (Join-Path $SteamVRPath "bin\win64\vrpathreg.exe") removedriver $driverDir
    Write-Host "Драйвер снят с регистрации." -ForegroundColor Green
} else {
    Write-Host "SteamVR не найден — драйвер уже не зарегистрирован или SteamVR удалён." -ForegroundColor Yellow
}

if ($steamRoot) {
    $settingsPath = Join-Path $steamRoot "config\steamvr.vrsettings"
    $backup = "$settingsPath.vrhand-backup"
    if (Test-Path $backup) {
        Copy-Item $backup $settingsPath -Force
        Remove-Item $backup
        Write-Host "Настройки SteamVR восстановлены из резервной копии." -ForegroundColor Green
    } elseif (Test-Path $settingsPath) {
        try {
            $json = Get-Content $settingsPath -Raw | ConvertFrom-Json
            if ($json.steamvr) {
                foreach ($name in @("forcedDriver", "activateMultipleDrivers", "enableHomeApp")) {
                    $json.steamvr.PSObject.Properties.Remove($name)
                }
                [System.IO.File]::WriteAllText($settingsPath, ($json | ConvertTo-Json -Depth 30), (New-Object System.Text.UTF8Encoding($false)))
                Write-Host "Параметры VRHand убраны из steamvr.vrsettings." -ForegroundColor Green
            }
        } catch {
            Write-Host "Не удалось поправить steamvr.vrsettings: уберите forcedDriver/activateMultipleDrivers/enableHomeApp вручную." -ForegroundColor Yellow
        }
    }
}
Write-Host "Готово."
