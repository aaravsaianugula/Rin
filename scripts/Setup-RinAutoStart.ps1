# Setup-RinAutoStart.ps1
# Creates a Windows Task Scheduler entry to run Rin Agent on startup

$ErrorActionPreference = "Stop"

$TaskName = "Rin Agent Background Service"
$ProjectPath = Split-Path $PSScriptRoot -Parent
$ScriptPath = Join-Path $ProjectPath "scripts\start_rin.bat"
$PythonwPath = Join-Path $ProjectPath "venv\Scripts\pythonw.exe"
$MainPyPath = Join-Path $ProjectPath "main.py"

Write-Host "Setting up Rin Agent to start on boot..." -ForegroundColor Cyan
Write-Host "Project Path: $ProjectPath"

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the action - run pythonw.exe with main.py (no console window)
if (Test-Path $PythonwPath) {
    $action = New-ScheduledTaskAction -Execute $PythonwPath -Argument "main.py" -WorkingDirectory $ProjectPath
}
else {
    # Fallback to system Python
    $action = New-ScheduledTaskAction -Execute "pythonw.exe" -Argument "main.py" -WorkingDirectory $ProjectPath
}

# Create the trigger - at user logon
$trigger = New-ScheduledTaskTrigger -AtLogon

# Create the principal - run as the current user
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Create settings
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

# Register the task
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description "Runs the Rin Agent backend on startup (Discord, Voice, API server)"
    
    Write-Host "`nSuccess! Rin Agent will now start automatically on login." -ForegroundColor Green
    Write-Host "Task Name: $TaskName"
    Write-Host "`nTo manage:" -ForegroundColor Cyan
    Write-Host "  - View: taskschd.msc (Task Scheduler)"
    Write-Host "  - Remove: Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
    Write-Host "  - Start now: Start-ScheduledTask -TaskName '$TaskName'"
    
    # Offer to start immediately
    $response = Read-Host "`nStart Rin Agent now? (y/n)"
    if ($response -eq 'y' -or $response -eq 'Y') {
        Start-ScheduledTask -TaskName $TaskName
        Write-Host "Started!" -ForegroundColor Green
    }
}
catch {
    Write-Host "Failed to create scheduled task: $_" -ForegroundColor Red
    Write-Host "`nAlternative: Add shortcut to shell:startup folder" -ForegroundColor Yellow
    
    # Create a shortcut in the startup folder as fallback
    $startupFolder = [Environment]::GetFolderPath('Startup')
    $shortcutPath = Join-Path $startupFolder "Rin Agent.lnk"
    
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $PythonwPath
    $shortcut.Arguments = "main.py"
    $shortcut.WorkingDirectory = $ProjectPath
    $shortcut.Description = "Rin Agent Background Service"
    $shortcut.WindowStyle = 7  # Minimized
    $shortcut.Save()
    
    Write-Host "Created startup shortcut at: $shortcutPath" -ForegroundColor Green
}
