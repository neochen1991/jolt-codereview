param(
  [switch]$InstallIfMissing,
  [switch]$SkipStaticTools
)

$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$ConfigPath = Join-Path $RootDir "config.json"
$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"

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
        throw ".venv is missing. Run scripts\install-windows.ps1 or start with -InstallIfMissing."
      }
      Write-Step "Creating Python virtual environment"
      if (Test-Command py) {
        py -3 -m venv .venv
      } elseif (Test-Command python) {
        python -m venv .venv
      } else {
        throw "Python 3 was not found. Install Python 3.10+ first."
      }
      & $VenvPython -m pip install --upgrade pip
      & $VenvPython -m pip install -r requirements.txt
    }
    if (-not (Test-Path $ConfigPath)) {
      if (Test-Path "config.example.json") {
        Copy-Item "config.example.json" "config.json"
      } else {
        throw "config.json is missing and config.example.json was not found."
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

$env:CONFIG_PATH = $ConfigPath
if (-not $env:PYTHON_BIN -and (Test-Path $VenvPython)) {
  $env:PYTHON_BIN = $VenvPython
}

Write-Step "Starting Jolt CodeReview"
Write-Host "API:      http://127.0.0.1:8011"
Write-Host "Frontend: http://127.0.0.1:5173"
Write-Host "Press Ctrl+C to stop all local services."

Push-Location $RootDir
try {
  npm run dev
} finally {
  Pop-Location
}
