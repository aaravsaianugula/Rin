# Install-RinService.ps1 — Register Rin Service as a Windows Startup Task
# Run as Administrator: powershell -ExecutionPolicy Bypass "path\to\Install-RinService.ps1"

param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "RinService"

# Resolve project root (script is in scripts/ subfolder)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
if (-not (Test-Path "$ProjectRoot\rin_service.py")) {
    Write-Error "Cannot find rin_service.py in $ProjectRoot"
    exit 1
}

$VbsLauncher = Join-Path $ScriptDir "start_rin_service.vbs"
if (-not (Test-Path $VbsLauncher)) {
    Write-Error "Cannot find start_rin_service.vbs in $ScriptDir"
    exit 1
}

if ($Uninstall) {
    Write-Host "[*] Removing Rin Service task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[OK] Rin Service uninstalled" -ForegroundColor Green
    exit 0
}

Write-Host "============================================"
Write-Host "  Rin Service Installer"
Write-Host "============================================"
Write-Host ""
Write-Host "Project Root : $ProjectRoot"
Write-Host "Launcher     : $VbsLauncher"
Write-Host "Task Name    : $TaskName"
Write-Host ""

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Remove stale lock file
Remove-Item "$ProjectRoot\logs\rin_service.lock" -Force -ErrorAction SilentlyContinue

# Create the scheduled task — runs at USER LOGON
# Uses wscript.exe + VBS to launch python.exe with a hidden window.
# This avoids pythonw.exe silent-crash issues under Task Scheduler.
$Action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$VbsLauncher`"" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -User "$env:USERDOMAIN\$env:USERNAME" `
    -RunLevel Highest `
    -Description "Rin Agent always-on service. Runs at logon, no console window. Enables mobile app connectivity." `
    -Force

Write-Host ""
Write-Host "[OK] Rin Service installed!" -ForegroundColor Green
Write-Host "  - Runs at user logon"
Write-Host "  - No terminal window (VBS hidden launcher)"
Write-Host "  - Restarts up to 5x on failure"
Write-Host "  - Listens on port 8000 for mobile app"
Write-Host ""

# Start it now
Write-Host "[*] Starting Rin Service now..."  -ForegroundColor Yellow
try {
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    # Wait up to 10 seconds for the service to become reachable
    $maxWait = 10
    for ($i = 0; $i -lt $maxWait; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) {
                Write-Host "[OK] Rin Service is running and healthy!" -ForegroundColor Green
                exit 0
            }
        }
        catch { }
    }
    Write-Host "[!] Task started but service not reachable yet. It will auto-start at next logon." -ForegroundColor Yellow
}
catch {
    Write-Host "[!] Could not start immediately: $_" -ForegroundColor Yellow
    Write-Host "    The service will start automatically at next logon." -ForegroundColor Yellow
}
