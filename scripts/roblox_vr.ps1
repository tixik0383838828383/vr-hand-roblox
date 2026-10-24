# Включает/выключает VR отдельно для Roblox Player и Roblox Studio.
# Запускать через roblox_vr.bat. Roblox и Studio при этом должны быть закрыты:
# при выходе они перезаписывают свои настройки.
param(
    [ValidateSet("PlayerOnly", "AllOff", "StudioOn", "Status")]
    [string]$Action = "Status"
)

$ErrorActionPreference = "Stop"
$dir = Join-Path $env:LOCALAPPDATA "Roblox"
$studioFile = Join-Path $dir "GlobalBasicSettings_13_Studio.xml"
$playerFile = Join-Path $dir "GlobalBasicSettings_13.xml"

function Get-Flag($file) {
    if (-not (Test-Path $file)) { return "(файла нет)" }
    $m = [regex]::Match((Get-Content $file -Raw), 'name="VREnabled"[^>]*>\s*(true|false)\s*<')
    if ($m.Success) { return $m.Groups[1].Value } else { return "(поля нет, считается false)" }
}

function Show-Status {
    Write-Host ""
    Write-Host "Папка настроек: $dir"
    Write-Host ("  Roblox Studio : VREnabled = {0}   [{1}]" -f (Get-Flag $studioFile), (Split-Path $studioFile -Leaf))
    Write-Host ("  Roblox Player : VREnabled = {0}   [{1}]" -f (Get-Flag $playerFile), (Split-Path $playerFile -Leaf))
}

function Set-Flag($file, [bool]$value, [string]$templateFile) {
    $text = if ($value) { "true" } else { "false" }
    if (-not (Test-Path $file)) {
        if ($templateFile -and (Test-Path $templateFile)) {
            Copy-Item $templateFile $file
            Write-Host "Создан $(Split-Path $file -Leaf) на основе $(Split-Path $templateFile -Leaf)"
        } elseif (-not $value) {
            return   # файла нет, VR и так выключен
        } else {
            $xml = '<roblox version="4"><Item class="UserGameSettings" referent="RBX0"><Properties><bool name="VREnabled">true</bool></Properties></Item></roblox>'
            [IO.File]::WriteAllText($file, $xml, (New-Object Text.UTF8Encoding($false)))
            Write-Host "Создан минимальный $(Split-Path $file -Leaf)"
            return
        }
    }
    $backup = "$file.vrhand-backup"
    if (-not (Test-Path $backup)) { Copy-Item $file $backup }
    $t = Get-Content $file -Raw
    if ($t -match 'name="VREnabled"') {
        $n = [regex]::Replace($t, '(name="VREnabled"[^>]*>)\s*(true|false)\s*(<)', ('${1}' + $text + '${3}'))
    } else {
        $n = $t -replace '</Properties>', ('<bool name="VREnabled">' + $text + '</bool></Properties>')
    }
    [IO.File]::WriteAllText($file, $n, (New-Object Text.UTF8Encoding($false)))
}

if ($Action -ne "Status") {
    $running = Get-Process -Name RobloxPlayerBeta, RobloxStudioBeta -ErrorAction SilentlyContinue
    if ($running) {
        Write-Host "ОШИБКА: Roblox или Studio сейчас запущен. Закройте их полностью (и значок в трее) и повторите." -ForegroundColor Red
        exit 1
    }
}

switch ($Action) {
    "PlayerOnly" {
        Set-Flag $studioFile $false $null
        Set-Flag $playerFile $true $studioFile
        Write-Host "Готово: VR включён в Roblox Player, в Studio выключен." -ForegroundColor Green
    }
    "AllOff" {
        Set-Flag $studioFile $false $null
        Set-Flag $playerFile $false $null
        Write-Host "Готово: VR выключен и в Player, и в Studio." -ForegroundColor Green
    }
    "StudioOn" {
        Set-Flag $studioFile $true $null
        Write-Host "Готово: VR включён в Studio (для тестов игр)." -ForegroundColor Green
    }
}
Show-Status
