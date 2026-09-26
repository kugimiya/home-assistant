#Requires -Version 5.1
# Repair venv, Python deps, and missing models/binaries. Does not install Python.
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Require-Python {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python not found in PATH. Install Python 3.11+ yourself, then run fix.ps1 again."
    }
    $version = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ([version]$version -lt [version]"3.11") {
        throw "Python $version is too old. Need 3.11+ (winget/install.ps1 not run — install manually)."
    }
    Write-Host "Using Python $version from $($python.Source)"
}

function Download-File {
    param(
        [string]$Url,
        [string]$Destination
    )
    Write-Host "Downloading $Url"
    Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing
}

$modelsDir = Join-Path $Root "models"
$thirdPartyDir = Join-Path $Root "third_party"
$piperDir = Join-Path $thirdPartyDir "piper"
New-Item -ItemType Directory -Force -Path $modelsDir, $thirdPartyDir, $piperDir | Out-Null

Require-Python

$piperZip = Join-Path $thirdPartyDir "piper_windows_amd64.zip"
if (-not (Test-Path (Join-Path $piperDir "piper.exe"))) {
    Download-File "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip" $piperZip
    $extractDir = Join-Path $thirdPartyDir "piper_extract"
    if (Test-Path $extractDir) {
        Remove-Item -Recurse -Force $extractDir
    }
    Expand-Archive -Path $piperZip -DestinationPath $extractDir -Force
    $piperExe = Get-ChildItem -Path $extractDir -Recurse -Filter "piper.exe" | Select-Object -First 1
    if (-not $piperExe) {
        throw "piper.exe not found in Piper archive"
    }
    Copy-Item -Recurse -Force $piperExe.Directory.FullName $piperDir
}

$voskZip = Join-Path $modelsDir "vosk-model-ru-0.42.zip"
$voskDir = Join-Path $modelsDir "vosk-model-ru-0.42"
if (-not (Test-Path $voskDir)) {
    Download-File "https://alphacephei.com/vosk/models/vosk-model-ru-0.42.zip" $voskZip
    Expand-Archive -Path $voskZip -DestinationPath $modelsDir -Force
}

$piperModel = Join-Path $modelsDir "ru_RU-irina-medium.onnx"
$piperConfig = Join-Path $modelsDir "ru_RU-irina-medium.onnx.json"
if (-not (Test-Path $piperModel)) {
    Download-File "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx" $piperModel
}
if (-not (Test-Path $piperConfig)) {
    Download-File "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx.json" $piperConfig
}

$venvPython = Join-Path $Root ".venv/Scripts/python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating .venv..."
    python -m venv .venv
}

Write-Host "Installing Python packages..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

Write-Host "Verifying imports..."
& $venvPython -c "import dotenv; import vosk; print('dotenv + vosk OK')"

$envExample = Join-Path $Root ".env.example"
$envFile = Join-Path $Root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item $envExample $envFile
    Write-Host "Created .env from .env.example"
}

Write-Host ""
Write-Host "Fix complete."
Write-Host "Run:"
Write-Host "  cd $Root"
Write-Host "  .\.venv\Scripts\python.exe -m jarvis_win"
