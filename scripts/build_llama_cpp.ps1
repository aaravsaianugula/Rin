<# 
    llama.cpp Build Script for AMD RX 6600 XT (Vulkan)
    
    This script builds llama.cpp with Vulkan support for AMD RDNA2 GPUs.
    ROCm/hipBLAS do NOT support gfx1032 (RX 6600 XT), so Vulkan is required.
#>

param(
    [string]$LlamaCppPath = (Join-Path (Split-Path $PSScriptRoot -Parent) "llama.cpp"),
    [switch]$Clean,
    [switch]$SkipClone
)

$ErrorActionPreference = "Stop"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "llama.cpp Vulkan Build Script" -ForegroundColor Cyan
Write-Host "Target: AMD RX 6600 XT (RDNA2/gfx1032)" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check for Vulkan SDK
$VulkanPath = $env:VULKAN_SDK
if (-not $VulkanPath) {
    Write-Host "ERROR: Vulkan SDK not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please install Vulkan SDK:" -ForegroundColor Yellow
    Write-Host "  1. Download from: https://vulkan.lunarg.com/sdk/home" -ForegroundColor Yellow
    Write-Host "  2. Install version 1.3.283 or later" -ForegroundColor Yellow
    Write-Host "  3. Restart your terminal after installation" -ForegroundColor Yellow
    exit 1
}
Write-Host "Vulkan SDK found: $VulkanPath" -ForegroundColor Green

# Check for CMake
try {
    $cmake = Get-Command cmake -ErrorAction Stop
    Write-Host "CMake found: $($cmake.Source)" -ForegroundColor Green
}
catch {
    Write-Host "ERROR: CMake not found!" -ForegroundColor Red
    Write-Host "Please install CMake from: https://cmake.org/download/" -ForegroundColor Yellow
    exit 1
}

# Check for Git
try {
    $git = Get-Command git -ErrorAction Stop
    Write-Host "Git found: $($git.Source)" -ForegroundColor Green
}
catch {
    Write-Host "ERROR: Git not found!" -ForegroundColor Red
    Write-Host "Please install Git from: https://git-scm.com/download/win" -ForegroundColor Yellow
    exit 1
}

Write-Host ""

# Clone or update llama.cpp
if (-not $SkipClone) {
    if (Test-Path $LlamaCppPath) {
        if ($Clean) {
            Write-Host "Removing existing llama.cpp directory..." -ForegroundColor Yellow
            Remove-Item -Recurse -Force $LlamaCppPath
        }
        else {
            Write-Host "Updating existing llama.cpp..." -ForegroundColor Yellow
            Push-Location $LlamaCppPath
            git pull
            Pop-Location
        }
    }
    
    if (-not (Test-Path $LlamaCppPath)) {
        Write-Host "Cloning llama.cpp..." -ForegroundColor Yellow
        git clone https://github.com/ggerganov/llama.cpp.git $LlamaCppPath
    }
}

# Navigate to llama.cpp directory
Push-Location $LlamaCppPath

# Create build directory
$BuildPath = Join-Path $LlamaCppPath "build"
if (Test-Path $BuildPath) {
    if ($Clean) {
        Write-Host "Cleaning build directory..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force $BuildPath
    }
}
New-Item -ItemType Directory -Force -Path $BuildPath | Out-Null

# Configure with CMake
Write-Host ""
Write-Host "Configuring with CMake (Vulkan enabled)..." -ForegroundColor Yellow
Push-Location $BuildPath

cmake .. -DGGML_VULKAN=ON -DCMAKE_BUILD_TYPE=Release

if ($LASTEXITCODE -ne 0) {
    Write-Host "CMake configuration failed!" -ForegroundColor Red
    Pop-Location
    Pop-Location
    exit 1
}

# Build
Write-Host ""
Write-Host "Building llama.cpp (this may take several minutes)..." -ForegroundColor Yellow
cmake --build . --config Release -j $env:NUMBER_OF_PROCESSORS

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    Pop-Location
    Pop-Location
    exit 1
}

Pop-Location  # Exit build directory
Pop-Location  # Exit llama.cpp directory

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "Build complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Binaries are located at:" -ForegroundColor Cyan
Write-Host "  $BuildPath\bin\Release\" -ForegroundColor White
Write-Host ""
Write-Host "To verify GPU detection, run:" -ForegroundColor Cyan
Write-Host "  $BuildPath\bin\Release\llama-cli.exe --list-devices" -ForegroundColor White
Write-Host ""
Write-Host "To start llama-server with Qwen3-VL:" -ForegroundColor Cyan
Write-Host "  $BuildPath\bin\Release\llama-server.exe ``" -ForegroundColor White
Write-Host "    -m models\Qwen3VL-4B-Instruct-Q4_K_M.gguf ``" -ForegroundColor White
Write-Host "    --mmproj models\mmproj-Qwen3VL-4B-Instruct-F16.gguf ``" -ForegroundColor White
Write-Host "    -ngl 40 -c 8192 --host 127.0.0.1 --port 8080" -ForegroundColor White
Write-Host ""
