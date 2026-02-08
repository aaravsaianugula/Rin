<#
.SYNOPSIS
    Rin - Unified Setup Wizard (Windows)
.DESCRIPTION
    One command to set up everything:
      powershell -ExecutionPolicy Bypass -File setup.ps1

    Phases:
      1. Prerequisites check
      2. Python environment
      3. Configuration and API key
      4. AI model selection and download
      5. llama.cpp build (GPU inference)
      6. Desktop overlay build and shortcuts
      7. Background service registration
      8. Mobile app setup (Tailscale)
#>

param(
    [switch]$SkipModels,
    [switch]$SkipVenv,
    [switch]$SkipLlama,
    [switch]$SkipOverlay,
    [switch]$SkipService,
    [switch]$SkipMobile,
    [switch]$Unattended,
    [string]$ModelChoice = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ProjectDir

# ── Helpers ───────────────────────────────────────

function Write-Banner {
    param([string]$Text, [string]$Color = "Cyan")
    $border = "=" * 48
    Write-Host ""
    Write-Host "  +$border+" -ForegroundColor $Color
    Write-Host "  |  $($Text.PadRight(46))|" -ForegroundColor $Color
    Write-Host "  +$border+" -ForegroundColor $Color
    Write-Host ""
}

function Write-Step {
    param([string]$Phase, [string]$Text)
    Write-Host "[$Phase] $Text" -ForegroundColor Yellow
}

function Write-OK {
    param([string]$Text)
    Write-Host "  [OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "  [!!] $Text" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Text)
    Write-Host "  [XX] $Text" -ForegroundColor Red
}

function Write-Detail {
    param([string]$Text)
    Write-Host "       $Text" -ForegroundColor DarkGray
}

function Test-CommandExists {
    param([string]$Command)
    try { Get-Command $Command -ErrorAction Stop | Out-Null; return $true }
    catch { return $false }
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Ask-YesNo {
    param([string]$Question, [bool]$Default = $true)
    if ($Unattended) { return $Default }
    $hint = if ($Default) { "(Y/n)" } else { "(y/N)" }
    $response = Read-Host "  $Question $hint"
    if ([string]::IsNullOrWhiteSpace($response)) { return $Default }
    return ($response.Trim().ToLower() -eq "y")
}

function Get-LanIP {
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 |
            Where-Object { $_.InterfaceAlias -notmatch "Loopback" -and $_.PrefixOrigin -eq "Dhcp" } |
            Select-Object -First 1).IPAddress
        if ($ip) { return $ip }
    }
    catch {}
    try {
        $ip = (Get-NetIPAddress -AddressFamily IPv4 |
            Where-Object { $_.InterfaceAlias -notmatch "Loopback" -and $_.IPAddress -match "^192\.168\." } |
            Select-Object -First 1).IPAddress
        if ($ip) { return $ip }
    }
    catch {}
    return "192.168.1.X"
}

# ── Track what was installed ──────────────────────

$Results = [ordered]@{}

# ==================================================
#  PHASE 0: Welcome
# ==================================================

Write-Banner "Rin - Setup Wizard"
Write-Host "  This wizard will set up Rin on your computer." -ForegroundColor White
Write-Host "  It checks prerequisites, installs dependencies," -ForegroundColor DarkGray
Write-Host "  downloads AI models, and configures everything." -ForegroundColor DarkGray
Write-Host ""

# ==================================================
#  PHASE 1: Prerequisites Check
# ==================================================

Write-Step "1/8" "Checking prerequisites..."

# Python (REQUIRED)
$HasPython = $false
try {
    $pyVersionRaw = python --version 2>&1
    if ($pyVersionRaw -match "Python\s+(\d+)\.(\d+)") {
        $pyMajor = [int]$Matches[1]
        $pyMinor = [int]$Matches[2]
        if ($pyMajor -ge 3 -and $pyMinor -ge 10) {
            Write-OK "Python $($pyMajor).$($pyMinor)"
            $HasPython = $true
        }
        else {
            Write-Fail "Python $($pyMajor).$($pyMinor) found (need 3.10+)"
        }
    }
}
catch {
    Write-Fail "Python not found"
}

if (-not $HasPython) {
    Write-Host ""
    Write-Host "  Python 3.10+ is required. Install from:" -ForegroundColor Red
    Write-Host "    https://www.python.org/downloads/" -ForegroundColor White
    Write-Host "    (Check 'Add Python to PATH' during install)" -ForegroundColor DarkGray
    Write-Host ""
    exit 1
}

# Git
$HasGit = Test-CommandExists "git"
if ($HasGit) { Write-OK "Git" }
else { Write-Warn "Git not found (needed for llama.cpp)" }

# .NET SDK
$HasDotnet = $false
try {
    $dotnetVer = dotnet --version 2>&1
    if ($dotnetVer -match "^\d+") {
        Write-OK ".NET SDK $dotnetVer"
        $HasDotnet = $true
    }
}
catch {}
if (-not $HasDotnet) {
    Write-Warn ".NET SDK not found (needed for desktop overlay)"
}

# Node.js
$HasNode = $false
try {
    $nodeVer = node --version 2>&1
    if ($nodeVer -match "v(\d+)") {
        $nodeMajor = [int]$Matches[1]
        if ($nodeMajor -ge 18) {
            Write-OK "Node.js $nodeVer"
            $HasNode = $true
        }
        else {
            Write-Warn "Node.js $nodeVer found (need 18+)"
        }
    }
}
catch {}
if (-not $HasNode) {
    Write-Warn "Node.js not found (needed for mobile app)"
}

# Vulkan SDK
$HasVulkan = -not [string]::IsNullOrEmpty($env:VULKAN_SDK)
if ($HasVulkan) { Write-OK "Vulkan SDK" }
else { Write-Warn "Vulkan SDK not found (GPU acceleration)" }

# CMake
$HasCMake = Test-CommandExists "cmake"
if ($HasCMake) { Write-OK "CMake" }
else { Write-Warn "CMake not found (needed for llama.cpp build)" }

# Admin check
$IsAdmin = Test-IsAdmin
if ($IsAdmin) { Write-OK "Running as Administrator" }
else { Write-Detail "Not admin - service registration will need a separate step" }

Write-Host ""

# ==================================================
#  PHASE 2: Python Environment
# ==================================================

Write-Step "2/8" "Setting up Python environment..."

if (-not $SkipVenv) {
    $VenvDir = Join-Path $ProjectDir "venv"
    if (-not (Test-Path $VenvDir)) {
        Write-Host "  Creating virtual environment..." -ForegroundColor DarkGray
        python -m venv $VenvDir
        Write-OK "Virtual environment created"
    }
    else {
        Write-OK "Virtual environment exists"
    }

    # Activate
    $ActivateScript = Join-Path $VenvDir "Scripts\Activate.ps1"
    if (Test-Path $ActivateScript) {
        . $ActivateScript
        Write-OK "Virtual environment activated"
    }
    else {
        Write-Warn "Could not activate venv (Scripts\Activate.ps1 missing)"
    }

    # Install dependencies
    Write-Host "  Installing Python packages..." -ForegroundColor DarkGray
    try {
        pip install -r (Join-Path $ProjectDir "requirements.txt") --quiet 2>&1 | Out-Null
        Write-OK "All Python packages installed"
    }
    catch {
        Write-Fail "pip install failed: $_"
        Write-Detail "Try manually: pip install -r requirements.txt"
    }
}
else {
    Write-Detail "Skipped (--SkipVenv)"
}

$Results["Python Environment"] = "[OK]"

# ==================================================
#  PHASE 3: Configuration and API Key
# ==================================================

Write-Step "3/8" "Setting up configuration..."

# Create directories
$Dirs = @(
    (Join-Path $ProjectDir "config\secrets"),
    (Join-Path $ProjectDir "logs"),
    (Join-Path $ProjectDir "data\memory"),
    (Join-Path $ProjectDir "models")
)
foreach ($d in $Dirs) {
    if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
}
Write-OK "Directories created"

# Copy .env.example -> .env
$envFile = Join-Path $ProjectDir ".env"
$envExample = Join-Path $ProjectDir ".env.example"
if (-not (Test-Path $envFile) -and (Test-Path $envExample)) {
    Copy-Item $envExample $envFile
    Write-OK "Created .env from template"
    Write-Detail "Edit .env later to add optional keys (Discord, Porcupine)"
}
elseif (Test-Path $envFile) {
    Write-OK ".env already configured"
}
else {
    Write-Warn ".env.example not found - creating minimal .env"
    Set-Content -Path $envFile -Value "# Rin Environment Variables`n# See .env.example for all options"
}

# Generate API key for mobile app authentication
$ApiKeyFile = Join-Path $ProjectDir "config\secrets\api_key.txt"
if (-not (Test-Path $ApiKeyFile)) {
    try {
        $pythonCmd = "import sys; sys.path.insert(0, '.'); from src.security import generate_api_key; key = generate_api_key(); print(key)"
        $apiKey = python -c $pythonCmd 2>&1
        if ($apiKey -and $apiKey.Length -ge 32) {
            Write-OK "API key generated for mobile app authentication"
            Write-Detail "Key saved to: config/secrets/api_key.txt"
        }
        else {
            Write-Warn "API key auto-generation needs first run - will generate on launch"
        }
    }
    catch {
        Write-Warn "API key will be generated on first run"
    }
}
else {
    Write-OK "API key already exists"
}

$Results["Configuration"] = "[OK]"

# ==================================================
#  PHASE 4: AI Model Selection and Download
# ==================================================

Write-Step "4/8" "AI Model Setup..."

if (-not $SkipModels) {
    # Determine which models are already downloaded
    $HasQwen = (Test-Path (Join-Path $ProjectDir "models\Qwen3VL-4B-Instruct-Q4_K_M.gguf"))
    $HasGemma = (Test-Path (Join-Path $ProjectDir "models\google_gemma-3-4b-it-Q4_K_M.gguf"))

    if ($HasQwen -and $HasGemma) {
        Write-OK "Both models already downloaded"
        $ModelChoice = "skip"
    }
    elseif ($HasQwen) {
        Write-OK "Qwen3-VL already downloaded"
        if (-not $HasGemma -and -not $ModelChoice) {
            if (Ask-YesNo "Also download Gemma 3? (~3.4 GB)" $false) {
                $ModelChoice = "gemma"
            }
            else { $ModelChoice = "skip" }
        }
    }
    elseif ($HasGemma) {
        Write-OK "Gemma 3 already downloaded"
        if (-not $HasQwen -and -not $ModelChoice) {
            if (Ask-YesNo "Also download Qwen3-VL? (~3.0 GB, recommended)" $true) {
                $ModelChoice = "qwen"
            }
            else { $ModelChoice = "skip" }
        }
    }

    # Interactive model selection
    if (-not $ModelChoice) {
        Write-Host ""
        Write-Host "  +===================================================+" -ForegroundColor Cyan
        Write-Host "  |     Select AI Model to Download                   |" -ForegroundColor Cyan
        Write-Host "  +===================================================+" -ForegroundColor Cyan
        Write-Host "  |                                                   |" -ForegroundColor Cyan
        Write-Host "  |  [1] Qwen3-VL 4B (Recommended)        ~3.0 GB    |" -ForegroundColor White
        Write-Host "  |      Best for computer control tasks              |" -ForegroundColor DarkGray
        Write-Host "  |                                                   |" -ForegroundColor Cyan
        Write-Host "  |  [2] Gemma 3 4B Vision                 ~3.4 GB   |" -ForegroundColor White
        Write-Host "  |      Google's multimodal model                    |" -ForegroundColor DarkGray
        Write-Host "  |                                                   |" -ForegroundColor Cyan
        Write-Host "  |  [3] Both models                       ~6.4 GB   |" -ForegroundColor White
        Write-Host "  |      Switch between them in settings              |" -ForegroundColor DarkGray
        Write-Host "  |                                                   |" -ForegroundColor Cyan
        Write-Host "  |  [4] Skip for now                                |" -ForegroundColor White
        Write-Host "  |      Download later with download_models.ps1      |" -ForegroundColor DarkGray
        Write-Host "  |                                                   |" -ForegroundColor Cyan
        Write-Host "  +===================================================+" -ForegroundColor Cyan
        Write-Host ""

        if ($Unattended) {
            $selection = "1"
        }
        else {
            $selection = Read-Host "  Enter choice (1-4)"
        }

        switch ($selection) {
            "1" { $ModelChoice = "qwen" }
            "2" { $ModelChoice = "gemma" }
            "3" { $ModelChoice = "both" }
            default { $ModelChoice = "skip" }
        }
    }

    # Download selected models
    if ($ModelChoice -ne "skip") {
        $downloadScript = Join-Path $ProjectDir "scripts\download_models.ps1"
        if (Test-Path $downloadScript) {
            $dlModel = if ($ModelChoice -eq "both") { "all" } else { $ModelChoice }
            Write-Host ""
            Write-Host "  Downloading models (this may take a while)..." -ForegroundColor DarkGray
            try {
                & $downloadScript -Model $dlModel -ModelsDir (Join-Path $ProjectDir "models")
                Write-OK "Models downloaded successfully"

                # Update settings.yaml active model based on selection
                $settingsPath = Join-Path $ProjectDir "config\settings.yaml"
                if (Test-Path $settingsPath) {
                    $settingsContent = Get-Content $settingsPath -Raw
                    if ($ModelChoice -eq "gemma" -and -not $HasQwen) {
                        $settingsContent = $settingsContent -replace "active_model: qwen3-vl-4b", "active_model: gemma-3-4b"
                        $settingsContent = $settingsContent -replace "main_model: models/Qwen3VL.*\.gguf", "main_model: models/google_gemma-3-4b-it-Q4_K_M.gguf"
                        $settingsContent = $settingsContent -replace "vision_projector: models/mmproj-Qwen3VL.*\.gguf", "vision_projector: models/mmproj-google_gemma-3-4b-it-bf16.gguf"
                        Set-Content -Path $settingsPath -Value $settingsContent
                        Write-OK "Active model set to Gemma 3 4B"
                    }
                    else {
                        Write-OK "Active model: Qwen3-VL 4B (default)"
                    }
                }
            }
            catch {
                Write-Fail "Model download failed: $_"
                Write-Detail "Try manually: .\scripts\download_models.ps1 -Model $dlModel"
            }
        }
        else {
            Write-Fail "Download script not found at $downloadScript"
        }
    }
    else {
        Write-Detail "Skipped model download"
        Write-Detail "Run later: .\scripts\download_models.ps1"
    }

    $Results["AI Models"] = if ($ModelChoice -ne "skip") { "[OK] Downloaded" } else { "[!!] Skipped" }
}
else {
    Write-Detail "Skipped (--SkipModels)"
    $Results["AI Models"] = "[!!] Skipped"
}

# ==================================================
#  PHASE 5: Build llama.cpp (GPU Inference Engine)
# ==================================================

Write-Step "5/8" "GPU Inference Engine (llama.cpp)..."

if (-not $SkipLlama) {
    $LlamaCppDir = Join-Path $ProjectDir "llama.cpp"
    $LlamaExe = Join-Path $LlamaCppDir "build\bin\Release\llama-server.exe"
    $UserProfileLlama = Join-Path $env:USERPROFILE "llama.cpp\build\bin\Release\llama-server.exe"

    # Check if already built somewhere
    if (Test-Path $LlamaExe) {
        Write-OK "llama.cpp already built (project-local)"
        $Results["llama.cpp"] = "[OK] Already built"
    }
    elseif (Test-Path $UserProfileLlama) {
        Write-OK "llama.cpp found in user profile"
        $Results["llama.cpp"] = "[OK] Found in USERPROFILE"
    }
    elseif (Test-CommandExists "llama-server") {
        Write-OK "llama-server found in PATH"
        $Results["llama.cpp"] = "[OK] In PATH"
    }
    else {
        # Need to build - check prerequisites
        $CanBuild = $HasGit -and $HasCMake

        if (-not $CanBuild) {
            Write-Warn "Cannot build llama.cpp - missing prerequisites:"
            if (-not $HasGit) { Write-Detail "Install Git:   https://git-scm.com/download/win" }
            if (-not $HasCMake) { Write-Detail "Install CMake: https://cmake.org/download/" }
            $Results["llama.cpp"] = "[!!] Missing prerequisites"
        }
        else {
            $shouldBuild = Ask-YesNo "Build llama.cpp for GPU inference? (takes ~5 min)" $true

            if ($shouldBuild) {
                Write-Host "  Cloning llama.cpp..." -ForegroundColor DarkGray
                try {
                    if (-not (Test-Path $LlamaCppDir)) {
                        git clone --depth 1 https://github.com/ggerganov/llama.cpp.git $LlamaCppDir 2>&1 | Out-Null
                    }

                    $BuildDir = Join-Path $LlamaCppDir "build"
                    New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
                    Push-Location $BuildDir

                    # Configure - Vulkan if available, otherwise CPU
                    if ($HasVulkan) {
                        Write-Host "  Configuring with Vulkan GPU support..." -ForegroundColor DarkGray
                        cmake .. -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release 2>&1 | Out-Null
                    }
                    else {
                        Write-Host "  Configuring CPU-only build (install Vulkan SDK for GPU)..." -ForegroundColor DarkGray
                        cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1 | Out-Null
                    }

                    if ($LASTEXITCODE -ne 0) { throw "CMake configure failed" }

                    # Build
                    $cores = $env:NUMBER_OF_PROCESSORS
                    Write-Host "  Building with $cores cores (this takes a few minutes)..." -ForegroundColor DarkGray
                    cmake --build . --config Release -j $cores 2>&1 | Out-Null

                    if ($LASTEXITCODE -ne 0) { throw "Build failed" }

                    Pop-Location

                    if (Test-Path $LlamaExe) {
                        $gpuNote = if ($HasVulkan) { "with Vulkan GPU" } else { "CPU-only" }
                        Write-OK "llama.cpp built ($gpuNote)"
                        $Results["llama.cpp"] = "[OK] Built ($gpuNote)"
                    }
                    else {
                        Write-Warn "Build completed but llama-server.exe not found at expected path"
                        $Results["llama.cpp"] = "[!!] Check manually"
                    }
                }
                catch {
                    if ((Get-Location).Path -ne $ProjectDir) { Pop-Location }
                    Write-Fail "Build failed: $_"
                    Write-Detail "Try manually: .\scripts\build_llama_cpp.ps1"
                    $Results["llama.cpp"] = "[XX] Failed"
                }
            }
            else {
                Write-Detail "Skipped llama.cpp build"
                Write-Detail "Build later: .\scripts\build_llama_cpp.ps1"
                $Results["llama.cpp"] = "[!!] Skipped"
            }
        }
    }
}
else {
    Write-Detail "Skipped (--SkipLlama)"
    $Results["llama.cpp"] = "[!!] Skipped"
}

# ==================================================
#  PHASE 6: Desktop Overlay (WPF Application)
# ==================================================

Write-Step "6/8" "Desktop overlay application..."

if (-not $SkipOverlay) {
    $CsprojPath = Join-Path $ProjectDir "OverlayApp\OverlayApp.csproj"

    if (-not $HasDotnet) {
        Write-Warn ".NET SDK not installed - skipping overlay build"
        Write-Detail "Install .NET 8 SDK: https://dotnet.microsoft.com/download"
        Write-Detail "Then run: .\scripts\Install-Rin.ps1"
        $Results["Desktop Overlay"] = "[!!] No .NET SDK"
    }
    elseif (-not (Test-Path $CsprojPath)) {
        Write-Fail "OverlayApp.csproj not found"
        $Results["Desktop Overlay"] = "[XX] Missing project file"
    }
    else {
        $shouldBuild = Ask-YesNo "Build desktop overlay and create shortcuts?" $true

        if ($shouldBuild) {
            Write-Host "  Building WPF overlay..." -ForegroundColor DarkGray
            try {
                dotnet build $CsprojPath -c Release --nologo -v q 2>&1 | Out-Null

                if ($LASTEXITCODE -ne 0) { throw "dotnet build failed" }

                Write-OK "Overlay built successfully"

                # Create shortcuts
                $TargetExe = Get-ChildItem -Path (Join-Path $ProjectDir "OverlayApp\bin\Release\net*") -Filter "OverlayApp.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1

                if ($TargetExe) {
                    $WshShell = New-Object -ComObject WScript.Shell
                    $IconPath = Join-Path $ProjectDir "OverlayApp\rin_logo.ico"
                    $AppName = "Rin Agent"

                    # Desktop shortcut
                    try {
                        $DesktopPath = [System.IO.Path]::Combine([Environment]::GetFolderPath("Desktop"), "$AppName.lnk")
                        $Shortcut = $WshShell.CreateShortcut($DesktopPath)
                        $Shortcut.TargetPath = $TargetExe.FullName
                        $Shortcut.WorkingDirectory = $ProjectDir
                        if (Test-Path $IconPath) { $Shortcut.IconLocation = $IconPath }
                        $Shortcut.Description = "Rin AI Assistant"
                        $Shortcut.Save()
                        Write-OK "Desktop shortcut created"
                    }
                    catch {
                        Write-Warn "Could not create desktop shortcut: $_"
                    }

                    # Start Menu shortcut
                    try {
                        $StartMenuPath = [System.IO.Path]::Combine([Environment]::GetFolderPath("Programs"), "$AppName.lnk")
                        $SMShortcut = $WshShell.CreateShortcut($StartMenuPath)
                        $SMShortcut.TargetPath = $TargetExe.FullName
                        $SMShortcut.WorkingDirectory = $ProjectDir
                        if (Test-Path $IconPath) { $SMShortcut.IconLocation = $IconPath }
                        $SMShortcut.Description = "Rin AI Assistant"
                        $SMShortcut.Save()
                        Write-OK "Start Menu shortcut created (searchable)"
                    }
                    catch {
                        Write-Warn "Could not create Start Menu shortcut: $_"
                    }
                }
                else {
                    Write-Warn "Built but could not find executable for shortcuts"
                }

                $Results["Desktop Overlay"] = "[OK] Built + shortcuts"
            }
            catch {
                Write-Fail "Overlay build failed: $_"
                Write-Detail "Try manually: dotnet build OverlayApp\OverlayApp.csproj -c Release"
                $Results["Desktop Overlay"] = "[XX] Build failed"
            }
        }
        else {
            Write-Detail "Skipped overlay build"
            $Results["Desktop Overlay"] = "[!!] Skipped"
        }
    }
}
else {
    Write-Detail "Skipped (--SkipOverlay)"
    $Results["Desktop Overlay"] = "[!!] Skipped"
}

# ==================================================
#  PHASE 7: Background Service Registration
# ==================================================

Write-Step "7/8" "Background service (always-on gateway)..."

if (-not $SkipService) {
    $VbsLauncher = Join-Path $ProjectDir "scripts\start_rin_service.vbs"

    if (-not (Test-Path $VbsLauncher)) {
        Write-Fail "start_rin_service.vbs not found"
        $Results["Service"] = "[XX] Launcher missing"
    }
    else {
        # Check if task already exists
        $existingTask = Get-ScheduledTask -TaskName "RinService" -ErrorAction SilentlyContinue

        if ($existingTask) {
            Write-OK "RinService already registered in Task Scheduler"
            $Results["Service"] = "[OK] Already registered"
        }
        else {
            $shouldRegister = Ask-YesNo "Register Rin as a background service (starts at login)?" $true

            if ($shouldRegister) {
                if (-not $IsAdmin) {
                    Write-Warn "Service registration requires Administrator privileges"
                    Write-Host ""
                    Write-Host "  To register the service, run this in an Admin PowerShell:" -ForegroundColor White
                    Write-Host "    powershell -ExecutionPolicy Bypass -File `"$ProjectDir\scripts\Install-RinService.ps1`"" -ForegroundColor Cyan
                    Write-Host ""
                    $Results["Service"] = "[!!] Needs admin"
                }
                else {
                    try {
                        $installScript = Join-Path $ProjectDir "scripts\Install-RinService.ps1"
                        if (Test-Path $installScript) {
                            & $installScript
                            $Results["Service"] = "[OK] Registered"
                        }
                        else {
                            # Manual registration as fallback
                            $Action = New-ScheduledTaskAction `
                                -Execute "wscript.exe" `
                                -Argument "`"$VbsLauncher`"" `
                                -WorkingDirectory $ProjectDir

                            $Trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

                            $Settings = New-ScheduledTaskSettingsSet `
                                -AllowStartIfOnBatteries `
                                -DontStopIfGoingOnBatteries `
                                -StartWhenAvailable `
                                -RestartCount 5 `
                                -RestartInterval (New-TimeSpan -Minutes 1) `
                                -ExecutionTimeLimit (New-TimeSpan -Days 365)

                            Register-ScheduledTask `
                                -TaskName "RinService" `
                                -Action $Action `
                                -Trigger $Trigger `
                                -Settings $Settings `
                                -User "$env:USERDOMAIN\$env:USERNAME" `
                                -RunLevel Highest `
                                -Description "Rin always-on gateway service. Enables mobile app connectivity." `
                                -Force

                            Write-OK "Service registered (starts at login)"

                            # Try to start now
                            try {
                                Start-ScheduledTask -TaskName "RinService" -ErrorAction Stop
                                Start-Sleep -Seconds 3
                                try {
                                    $health = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 5
                                    if ($health.StatusCode -eq 200) {
                                        Write-OK "Service is running and healthy!"
                                    }
                                }
                                catch {
                                    Write-OK "Service started (may still be initializing)"
                                }
                            }
                            catch {
                                Write-Detail "Service will start automatically at next login"
                            }

                            $Results["Service"] = "[OK] Registered"
                        }
                    }
                    catch {
                        Write-Fail "Service registration failed: $_"
                        Write-Detail "Run manually as admin: .\scripts\Install-RinService.ps1"
                        $Results["Service"] = "[XX] Failed"
                    }
                }
            }
            else {
                Write-Detail "Skipped service registration"
                Write-Detail "Register later: .\scripts\Install-RinService.ps1"
                $Results["Service"] = "[!!] Skipped"
            }
        }
    }
}
else {
    Write-Detail "Skipped (--SkipService)"
    $Results["Service"] = "[!!] Skipped"
}

# ==================================================
#  PHASE 8: Mobile App Setup
# ==================================================

Write-Step "8/8" "Mobile app setup..."

if (-not $SkipMobile) {
    $MobileDir = Join-Path $ProjectDir "mobile"

    if (-not (Test-Path $MobileDir)) {
        Write-Warn "mobile/ directory not found"
        $Results["Mobile App"] = "[XX] Missing directory"
    }
    else {
        $shouldSetupMobile = Ask-YesNo "Set up mobile app (React Native)?" $true

        if ($shouldSetupMobile) {
            # Install npm dependencies
            if ($HasNode) {
                $NodeModules = Join-Path $MobileDir "node_modules"
                if (-not (Test-Path $NodeModules)) {
                    Write-Host "  Installing mobile dependencies..." -ForegroundColor DarkGray
                    try {
                        Push-Location $MobileDir
                        npm install --loglevel error 2>&1 | Out-Null
                        Pop-Location
                        Write-OK "Mobile dependencies installed"
                    }
                    catch {
                        if ((Get-Location).Path -ne $ProjectDir) { Pop-Location }
                        Write-Warn "npm install failed - try manually: cd mobile && npm install"
                    }
                }
                else {
                    Write-OK "Mobile dependencies already installed"
                }
            }
            else {
                Write-Warn "Node.js not installed - install from https://nodejs.org"
                Write-Detail "Then run: cd mobile && npm install"
            }

            # ── Mobile Connection Guide ──
            $LanIP = Get-LanIP

            Write-Host ""
            Write-Host "  +===================================================+" -ForegroundColor Magenta
            Write-Host "  |         Mobile App Connection Guide               |" -ForegroundColor Magenta
            Write-Host "  +===================================================+" -ForegroundColor Magenta
            Write-Host ""
            Write-Host "  Your phone needs to reach this PC." -ForegroundColor White
            Write-Host "  Choose one of the two options below:" -ForegroundColor White
            Write-Host ""

            # Option A: Tailscale (recommended)
            Write-Host "  -- Option A: Tailscale (Recommended) ----------" -ForegroundColor Cyan
            Write-Host "  Tailscale creates a secure private network between" -ForegroundColor DarkGray
            Write-Host "  your devices. Works anywhere - home, office, LTE." -ForegroundColor DarkGray
            Write-Host ""
            Write-Host "  Step 1: Install Tailscale" -ForegroundColor White
            Write-Host "    * On this PC:   https://tailscale.com/download/windows" -ForegroundColor DarkGray
            Write-Host "    * On your phone: App Store / Google Play -> 'Tailscale'" -ForegroundColor DarkGray
            Write-Host ""
            Write-Host "  Step 2: Sign in on both devices with the same account" -ForegroundColor White
            Write-Host "    (Google, Microsoft, or GitHub login)" -ForegroundColor DarkGray
            Write-Host ""
            Write-Host "  Step 3: Find your PC's Tailscale IP" -ForegroundColor White
            Write-Host "    * Open Tailscale on PC -> hover over your machine" -ForegroundColor DarkGray
            Write-Host "    * It will show an IP like 100.x.x.x" -ForegroundColor DarkGray
            Write-Host ""
            Write-Host "  Step 4: Enter that IP in the Rin mobile app settings" -ForegroundColor White
            Write-Host "    * Open Rin app -> Settings -> Server Host -> 100.x.x.x" -ForegroundColor DarkGray
            Write-Host "    * Port: 8000 (default)" -ForegroundColor DarkGray
            Write-Host ""

            # Option B: Same Wi-Fi
            Write-Host "  -- Option B: Same Wi-Fi Network ---------------" -ForegroundColor Cyan
            Write-Host "  Works only when phone and PC are on the same network." -ForegroundColor DarkGray
            Write-Host ""
            Write-Host "  Your PC's LAN IP: $LanIP" -ForegroundColor White
            Write-Host ""
            Write-Host "  Step 1: Open Rin app -> Settings -> Server Host" -ForegroundColor White
            Write-Host "  Step 2: Enter: $LanIP" -ForegroundColor White
            Write-Host "  Step 3: Port: 8000 | Enter the API key from:" -ForegroundColor White
            Write-Host "          config\secrets\api_key.txt" -ForegroundColor DarkGray
            Write-Host ""

            # Firewall note
            Write-Host "  -- Firewall -----------------------------------" -ForegroundColor Cyan
            Write-Host "  If your phone can't connect, allow port 8000:" -ForegroundColor DarkGray
            Write-Host ""

            # Try to add firewall rule automatically
            if ($IsAdmin) {
                try {
                    $existingRule = Get-NetFirewallRule -DisplayName "Rin Service" -ErrorAction SilentlyContinue
                    if (-not $existingRule) {
                        New-NetFirewallRule -DisplayName "Rin Service" `
                            -Direction Inbound -Protocol TCP -LocalPort 8000 `
                            -Action Allow -Profile @('Private', 'Domain') `
                            -Description "Allow Rin mobile app connections" | Out-Null
                        Write-OK "Firewall rule added (port 8000, private networks)"
                    }
                    else {
                        Write-OK "Firewall rule already exists"
                    }
                }
                catch {
                    Write-Detail "Run as admin: New-NetFirewallRule -DisplayName 'Rin Service' -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow"
                }
            }
            else {
                Write-Host "  Run in Admin PowerShell:" -ForegroundColor White
                Write-Host "  New-NetFirewallRule -DisplayName 'Rin Service' ``" -ForegroundColor DarkGray
                Write-Host "    -Direction Inbound -Protocol TCP -LocalPort 8000 ``" -ForegroundColor DarkGray
                Write-Host "    -Action Allow -Profile Private" -ForegroundColor DarkGray
            }
            Write-Host ""

            # ── Build APK ──
            Write-Host "  -- Building APK --------------------------------" -ForegroundColor Cyan
            Write-Host ""

            # Check for existing APK
            $ApkDest = Join-Path $ProjectDir "Rin.apk"

            if ((Test-Path $ApkDest) -and -not (Ask-YesNo "APK already exists at Rin.apk. Rebuild?" $false)) {
                Write-OK "Using existing APK: Rin.apk"
                Write-Detail "Transfer Rin.apk to your phone and install"
            }
            else {
                # Check prerequisites for APK build
                $HasAndroidSdk = $false
                $AndroidSdkPath = $null
                if ($env:ANDROID_HOME -and (Test-Path $env:ANDROID_HOME)) {
                    $HasAndroidSdk = $true
                    $AndroidSdkPath = $env:ANDROID_HOME
                }
                elseif ($env:ANDROID_SDK_ROOT -and (Test-Path $env:ANDROID_SDK_ROOT)) {
                    $HasAndroidSdk = $true
                    $AndroidSdkPath = $env:ANDROID_SDK_ROOT
                }
                else {
                    $DefaultSdk = Join-Path $env:LOCALAPPDATA "Android\Sdk"
                    if (Test-Path $DefaultSdk) {
                        $HasAndroidSdk = $true
                        $AndroidSdkPath = $DefaultSdk
                    }
                }

                $HasJava = Test-CommandExists "java"

                if ($HasAndroidSdk -and $HasNode -and $HasJava) {
                    $shouldBuildApk = Ask-YesNo "Build APK now? (takes a few minutes)" $true

                    if ($shouldBuildApk) {
                        # Use short path to avoid Windows 260-char limit
                        $ShortBuildPath = "C:\rin_build"
                        $UseShortPath = $ProjectDir.Length -gt 40

                        try {
                            $BuildMobileDir = $MobileDir
                            if ($UseShortPath) {
                                Write-Detail "Using short build path to avoid Windows path limit..."
                                if (Test-Path $ShortBuildPath) {
                                    Remove-Item $ShortBuildPath -Recurse -Force
                                }
                                New-Item -ItemType Directory -Path $ShortBuildPath -Force | Out-Null

                                # Copy mobile source (exclude node_modules - reinstall fresh)
                                Write-Detail "Copying mobile source to $ShortBuildPath..."
                                robocopy $MobileDir $ShortBuildPath /E /NFL /NDL /NJH /NJS /NP /XD node_modules .expo | Out-Null
                                $BuildMobileDir = $ShortBuildPath

                                # Clean android build dirs in short path
                                $AndroidBuildDirs = @(
                                    (Join-Path $ShortBuildPath "android\build"),
                                    (Join-Path $ShortBuildPath "android\.gradle"),
                                    (Join-Path $ShortBuildPath "android\app\build")
                                )
                                foreach ($bd in $AndroidBuildDirs) {
                                    if (Test-Path $bd) { Remove-Item $bd -Recurse -Force -ErrorAction SilentlyContinue }
                                }

                                # Fresh npm install in short path
                                Write-Detail "Installing dependencies in short path..."
                                Push-Location $ShortBuildPath
                                npm install --loglevel error 2>&1 | Out-Null
                                Pop-Location
                            }

                            # Run expo prebuild if android dir needs refresh
                            $AndroidDir = Join-Path $BuildMobileDir "android"
                            if (-not (Test-Path (Join-Path $AndroidDir "gradlew.bat"))) {
                                Write-Detail "Running expo prebuild..."
                                Push-Location $BuildMobileDir
                                npx expo prebuild --platform android --clean 2>&1 | Out-Null
                                Pop-Location
                            }

                            # Build the APK
                            $GradlewPath = Join-Path $AndroidDir "gradlew.bat"
                            if (Test-Path $GradlewPath) {
                                Write-Host "  Building APK (this takes 2-5 minutes)..." -ForegroundColor DarkGray
                                Push-Location $AndroidDir

                                # Set ANDROID_HOME if not set
                                if (-not $env:ANDROID_HOME) {
                                    $env:ANDROID_HOME = $AndroidSdkPath
                                }

                                & .\gradlew.bat assembleDebug --no-daemon -q 2>&1 | Out-Null
                                $buildExitCode = $LASTEXITCODE
                                Pop-Location

                                if ($buildExitCode -eq 0) {
                                    # Find the built APK
                                    $BuiltApk = Get-ChildItem -Path (Join-Path $AndroidDir "app\build\outputs\apk") -Recurse -Filter "*.apk" -ErrorAction SilentlyContinue |
                                    Sort-Object LastWriteTime -Descending |
                                    Select-Object -First 1

                                    if ($BuiltApk) {
                                        # Copy APK to project root for easy access
                                        Copy-Item $BuiltApk.FullName $ApkDest -Force
                                        $apkSizeMB = [math]::Round($BuiltApk.Length / 1MB, 1)
                                        Write-OK "APK built successfully ($($apkSizeMB) MB)"
                                        Write-OK "Saved to: Rin.apk"
                                        Write-Detail "Transfer Rin.apk to your phone and install"
                                    }
                                    else {
                                        Write-Warn "Build finished but APK not found"
                                    }
                                }
                                else {
                                    Write-Fail "Gradle build failed (exit code $buildExitCode)"
                                    Write-Detail "Try manually: cd mobile\android && .\gradlew.bat assembleDebug"
                                }
                            }
                            else {
                                Write-Fail "gradlew.bat not found - run 'npx expo prebuild' first"
                            }

                            # Clean up short build path
                            if ($UseShortPath -and (Test-Path $ShortBuildPath)) {
                                Write-Detail "Cleaning up build directory..."
                                Remove-Item $ShortBuildPath -Recurse -Force -ErrorAction SilentlyContinue
                            }
                        }
                        catch {
                            if ((Get-Location).Path -ne $ProjectDir) { Pop-Location }
                            Write-Fail "APK build failed: $_"
                            Write-Detail "Try manually: cd mobile && npx expo prebuild && cd android && .\gradlew.bat assembleDebug"

                            # Clean up on failure
                            if ($UseShortPath -and (Test-Path $ShortBuildPath)) {
                                Remove-Item $ShortBuildPath -Recurse -Force -ErrorAction SilentlyContinue
                            }
                        }
                    }
                    else {
                        Write-Detail "Skipped APK build"
                        Write-Detail "Build later: cd mobile && npx expo prebuild && cd android && .\gradlew.bat assembleDebug"
                    }
                }
                else {
                    Write-Warn "Cannot build APK - missing prerequisites:"
                    if (-not $HasAndroidSdk) { Write-Detail "Android SDK: Install Android Studio from https://developer.android.com/studio" }
                    if (-not $HasJava) { Write-Detail "Java: Install JDK 17 from https://adoptium.net" }
                    if (-not $HasNode) { Write-Detail "Node.js: Install from https://nodejs.org" }
                    Write-Host ""
                    Write-Host "  Manual build after installing prerequisites:" -ForegroundColor White
                    Write-Host "    cd mobile" -ForegroundColor DarkGray
                    Write-Host "    npx expo prebuild" -ForegroundColor DarkGray
                    Write-Host "    cd android" -ForegroundColor DarkGray
                    Write-Host "    .\gradlew.bat assembleDebug" -ForegroundColor DarkGray
                }
            }
            Write-Host ""

            $Results["Mobile App"] = "[OK] Configured"
        }
        else {
            Write-Detail "Skipped mobile setup"
            $Results["Mobile App"] = "[!!] Skipped"
        }
    }
}
else {
    Write-Detail "Skipped (--SkipMobile)"
    $Results["Mobile App"] = "[!!] Skipped"
}

# ==================================================
#  Summary
# ==================================================

Write-Host ""
Write-Banner "Setup Complete!" "Green"

# Results table
Write-Host "  Component              Status" -ForegroundColor White
Write-Host "  ---------------------  -------------------" -ForegroundColor DarkGray
foreach ($key in $Results.Keys) {
    $status = $Results[$key]
    $color = "White"
    if ($status -match "^\[OK\]") { $color = "Green" }
    elseif ($status -match "^\[!!\]") { $color = "Yellow" }
    elseif ($status -match "^\[XX\]") { $color = "Red" }
    Write-Host "  $($key.PadRight(23)) $status" -ForegroundColor $color
}
Write-Host ""

# Quick start instructions
Write-Host "  -- Quick Start --------------------------------" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Start Rin (interactive):" -ForegroundColor White
Write-Host "    python main.py" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Start service (background):" -ForegroundColor White
Write-Host "    Start-ScheduledTask -TaskName 'RinService'" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Open overlay:" -ForegroundColor White
Write-Host "    Search 'Rin Agent' in Start Menu" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Mobile app:" -ForegroundColor White
Write-Host "    Configure server IP in app Settings" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Documentation: README.md" -ForegroundColor DarkGray
Write-Host ""
