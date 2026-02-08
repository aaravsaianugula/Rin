# Rin Installation & Registration Script
# This script builds the Rin app and creates shortcuts for professional integration.

$ProjectDir = Get-Location
$AppName = "Rin Agent"
$WpfProjPath = Join-Path $ProjectDir "OverlayApp\OverlayApp.csproj"
$IconPath = Join-Path $ProjectDir "OverlayApp\rin_logo.ico"

Write-Host "--- Packaging Rin AI Assistant ---" -ForegroundColor Cyan

# 1. Build the WPF Application
Write-Host "Building WPF Application..."
dotnet build $WpfProjPath -c Release
if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed!"
    exit $LASTEXITCODE
}

# Find the executable
$TargetExe = Get-ChildItem -Path (Join-Path $ProjectDir "OverlayApp\bin\Release\net*") -Filter "$AppName.exe" -Recurse | Select-Object -First 1
if (-not $TargetExe) {
    Write-Error "Could not find built executable!"
    exit 1
}

$ExePath = $TargetExe.FullName
Write-Host "Executable found at: $ExePath"

# 2. Create Shortcuts
$WshShell = New-Object -ComObject WScript.Shell

# Desktop Shortcut
Write-Host "Creating Desktop shortcut..."
$DesktopPath = [System.IO.Path]::Combine([System.Environment]::GetFolderPath("Desktop"), "$AppName.lnk")
$Shortcut = $WshShell.CreateShortcut($DesktopPath)
$Shortcut.TargetPath = $ExePath
$Shortcut.WorkingDirectory = $ProjectDir # Main directory so python can find scripts
$Shortcut.IconLocation = $IconPath
$Shortcut.Description = "Rin AI Assistant Control Center"
$Shortcut.Save()

# Start Menu Registration (Searchable)
Write-Host "Registering in Start Menu..."
$StartMenuPath = [System.IO.Path]::Combine([System.Environment]::GetFolderPath("Programs"), "$AppName.lnk")
$StartMenuShortcut = $WshShell.CreateShortcut($StartMenuPath)
$StartMenuShortcut.TargetPath = $ExePath
$StartMenuShortcut.WorkingDirectory = $ProjectDir
$StartMenuShortcut.IconLocation = $IconPath
$StartMenuShortcut.Description = "Rin AI Assistant"
$StartMenuShortcut.Save()

Write-Host "--- SUCCESS ---" -ForegroundColor Green
Write-Host "Rin is now installed and searchable in your Start Menu."
Write-Host "Double-click the desktop icon to launch."
