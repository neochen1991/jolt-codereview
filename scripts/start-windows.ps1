param(
  [switch]$InstallIfMissing,
  [switch]$SkipStaticTools
)

$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$CommonConfigPath = Join-Path $RootDir "common-backend\config.json"
$MrConfigPath = Join-Path $RootDir "mr-backend\config.json"
$VenvPython = Join-Path $RootDir "mr-backend\.venv\Scripts\python.exe"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "[$(Get-Date -Format HH:mm:ss)] $Message" -ForegroundColor Cyan
}

function Test-Command {
  param([string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-ProjectReady {
  Push-Location $RootDir
  try {
    if (-not (Test-Command node)) {
      throw "Node.js was not found. Install Node.js 24+ first, then rerun scripts\install-windows.ps1."
    }
    if (-not (Test-Command npm)) {
      throw "npm was not found. Install Node.js 24+ first, then rerun scripts\install-windows.ps1."
    }
    if (-not (Test-Path "node_modules")) {
      if (-not $InstallIfMissing) {
        throw "node_modules is missing. Run scripts\install-windows.ps1 or start with -InstallIfMissing."
      }
      Write-Step "Installing npm dependencies"
      npm install
    }
    if (-not (Test-Path $VenvPython)) {
      if (-not $InstallIfMissing) {
        throw "mr-backend\.venv is missing. Run scripts\install-windows.ps1 or start with -InstallIfMissing."
      }
      Write-Step "Creating Python virtual environment"
      if (Test-Command py) {
        py -3 -m venv "mr-backend\.venv"
      } elseif (Test-Command python) {
        python -m venv "mr-backend\.venv"
      } else {
        throw "Python 3 was not found. Install Python 3.10+ first."
      }
      & $VenvPython -m pip install --upgrade pip
      & $VenvPython -m pip install -r "mr-backend\requirements.txt"
    }
    Write-Step "Checking runtime package dependencies"
    $depArgs = @("scripts/check-runtime-deps.mjs")
    if ($InstallIfMissing) { $depArgs += "--install" }
    node @depArgs
    if (-not (Test-Path $CommonConfigPath)) {
      $commonExample = Join-Path $RootDir "common-backend\config.example.json"
      if (Test-Path $commonExample) {
        Copy-Item $commonExample $CommonConfigPath
      } else {
        throw "common-backend\config.json is missing and common-backend\config.example.json was not found."
      }
    }
    if (-not (Test-Path $MrConfigPath)) {
      $mrExample = Join-Path $RootDir "mr-backend\config.example.json"
      if (Test-Path $mrExample) {
        Copy-Item $mrExample $MrConfigPath
      } else {
        throw "mr-backend\config.json is missing and mr-backend\config.example.json was not found."
      }
    }
    if ($InstallIfMissing -and (-not $SkipStaticTools)) {
      Write-Step "Verifying static tools"
      .\scripts\install-windows.ps1 -VerifyOnly
    }
  } finally {
    Pop-Location
  }
}

Ensure-ProjectReady

$env:COMMON_CONFIG_PATH = $CommonConfigPath
$env:MR_CONFIG_PATH = $MrConfigPath
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
if (-not $env:PYTHON_BIN -and (Test-Path $VenvPython)) {
  $env:PYTHON_BIN = $VenvPython
}
try {
  chcp 65001 | Out-Null
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  [Console]::InputEncoding = [System.Text.Encoding]::UTF8
} catch {
  Write-Warning "Failed to switch console encoding to UTF-8. Continuing with PYTHONUTF8/PYTHONIOENCODING."
}

Write-Step "Starting Jolt CodeReview"
Write-Host "Common:    http://127.0.0.1:9022"
Write-Host "MR Backend:http://127.0.0.1:9021"
Write-Host "Frontend:  http://127.0.0.1:9020"
Write-Host "Press Ctrl+C to stop all local services."

Push-Location $RootDir
try {
  npm run dev
} finally {
  Pop-Location
}
