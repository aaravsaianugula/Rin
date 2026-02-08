<# 
    Download VLM Model Files from Hugging Face
    
    Downloads the required GGUF model files for the computer control system.
    Supports: Qwen3-VL 4B, Gemma 3 4B Vision
#>

param(
    [string]$ModelsDir = ".\models",
    [switch]$Force,
    [string]$Model = "all"  # "all", "qwen", or "gemma"
)

$ErrorActionPreference = "Stop"

# Model URLs
$QwenModels = @(
    [PSCustomObject]@{
        Name = "Qwen3VL-4B-Instruct-Q4_K_M.gguf"
        Url  = "https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/main/Qwen3VL-4B-Instruct-Q4_K_M.gguf"
        Size = "~2.5 GB"
    },
    [PSCustomObject]@{
        Name = "mmproj-Qwen3VL-4B-Instruct-F16.gguf"
        Url  = "https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/main/mmproj-Qwen3VL-4B-Instruct-F16.gguf"
        Size = "~500 MB"
    }
)

$GemmaModels = @(
    [PSCustomObject]@{
        Name = "google_gemma-3-4b-it-Q4_K_M.gguf"
        Url  = "https://huggingface.co/bartowski/google_gemma-3-4b-it-GGUF/resolve/main/google_gemma-3-4b-it-Q4_K_M.gguf"
        Size = "~2.5 GB"
    },
    [PSCustomObject]@{
        Name = "mmproj-google_gemma-3-4b-it-bf16.gguf"
        Url  = "https://huggingface.co/bartowski/google_gemma-3-4b-it-GGUF/resolve/main/mmproj-google_gemma-3-4b-it-bf16.gguf"
        Size = "~900 MB"
    }
)

# Select models to download
$Models = [System.Collections.ArrayList]@()
if ($Model -eq "all" -or $Model -eq "qwen") { $Models.AddRange($QwenModels) }
if ($Model -eq "all" -or $Model -eq "gemma") { $Models.AddRange($GemmaModels) }

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "VLM Model Downloader" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Create models directory
if (-not (Test-Path $ModelsDir)) {
    New-Item -ItemType Directory -Path $ModelsDir | Out-Null
    Write-Host "Created directory: $ModelsDir" -ForegroundColor Green
}

# Download each model
foreach ($model in $Models) {
    $targetPath = Join-Path $ModelsDir $model.Name
    
    if ((Test-Path $targetPath) -and (-not $Force)) {
        Write-Host "Skipping $($model.Name) (already exists)" -ForegroundColor Yellow
        Write-Host "  Use -Force to re-download" -ForegroundColor Gray
        continue
    }
    
    Write-Host ""
    Write-Host "Downloading $($model.Name) ($($model.Size))..." -ForegroundColor Yellow
    Write-Host "  From: $($model.Url)" -ForegroundColor Gray
    Write-Host ""
    
    try {
        # Use BITS for better download experience with large files
        $webClient = New-Object System.Net.WebClient
        $webClient.DownloadFile($model.Url, $targetPath)
        Write-Host "Downloaded: $($model.Name)" -ForegroundColor Green
    }
    catch {
        Write-Host "Failed to download $($model.Name): $_" -ForegroundColor Red
        Write-Host ""
        Write-Host "Manual download:" -ForegroundColor Yellow
        Write-Host "  1. Visit: $($model.Url)" -ForegroundColor White
        Write-Host "  2. Save to: $targetPath" -ForegroundColor White
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "Download complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Model files in: $ModelsDir" -ForegroundColor Cyan
Get-ChildItem $ModelsDir -Filter "*.gguf" | ForEach-Object {
    $sizeMB = [math]::Round($_.Length / 1MB, 2)
    Write-Host "  $($_.Name) ($sizeMB MB)" -ForegroundColor White
}
Write-Host ""
