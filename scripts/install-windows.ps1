param(
  [string]$ToolHome = "$env:USERPROFILE\.jolt-tools",
  [switch]$SkipWinget,
  [switch]$SkipProjectDeps,
  [switch]$SkipStaticTools,
  [switch]$SkipStaticRules,
  [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
try {
  chcp 65001 | Out-Null
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  [Console]::InputEncoding = [System.Text.Encoding]::UTF8
} catch {
  Write-Warning "Failed to switch console encoding to UTF-8. Continuing with PYTHONUTF8/PYTHONIOENCODING."
}

$GitleaksVersion = $env:GITLEAKS_VERSION
if (-not $GitleaksVersion) { $GitleaksVersion = "8.30.1" }
$PmdVersion = $env:PMD_VERSION
if (-not $PmdVersion) { $PmdVersion = "7.25.0" }
$CheckstyleVersion = $env:CHECKSTYLE_VERSION
if (-not $CheckstyleVersion) { $CheckstyleVersion = "13.5.0" }
$SpotbugsVersion = $env:SPOTBUGS_VERSION
if (-not $SpotbugsVersion) { $SpotbugsVersion = "4.9.8" }
$DependencyCheckVersion = $env:DEPENDENCY_CHECK_VERSION
if (-not $DependencyCheckVersion) { $DependencyCheckVersion = "12.2.2" }
$OsvScannerVersion = $env:OSV_SCANNER_VERSION
if (-not $OsvScannerVersion) { $OsvScannerVersion = "2.3.8" }
$TrivyVersion = $env:TRIVY_VERSION
if (-not $TrivyVersion) { $TrivyVersion = "0.71.0" }
$KicsVersion = $env:KICS_VERSION
if (-not $KicsVersion) { $KicsVersion = "2.1.20" }

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$BinDir = Join-Path $ToolHome "bin"
$TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("jolt-install-" + [Guid]::NewGuid().ToString("N"))

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "[$(Get-Date -Format HH:mm:ss)] $Message" -ForegroundColor Cyan
}

function Write-Warn {
  param([string]$Message)
  Write-Warning $Message
}

function Test-Command {
  param([string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Add-Path {
  param([string]$PathValue)
  if (-not (Test-Path $PathValue)) {
    New-Item -ItemType Directory -Path $PathValue -Force | Out-Null
  }
  $parts = $env:Path -split ";"
  if ($parts -notcontains $PathValue) {
    $env:Path = "$PathValue;$env:Path"
  }
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $userParts = @()
  if ($userPath) { $userParts = $userPath -split ";" }
  if ($userParts -notcontains $PathValue) {
    $newUserPath = if ($userPath) { "$PathValue;$userPath" } else { $PathValue }
    [Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
  }
}

function Refresh-Path {
  $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machinePath;$userPath;$env:Path"
}

function Invoke-Download {
  param([string]$Url, [string]$OutFile)
  Write-Host "Downloading $Url"
  Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing
}

function Expand-Zip {
  param([string]$ZipPath, [string]$Destination)
  if (Test-Path $Destination) {
    Remove-Item $Destination -Recurse -Force
  }
  New-Item -ItemType Directory -Path $Destination -Force | Out-Null
  Expand-Archive -Path $ZipPath -DestinationPath $Destination -Force
}

function Install-WingetPackage {
  param([string]$CommandName, [string]$PackageId)
  if (Test-Command $CommandName) { return }
  if ($SkipWinget -or -not (Test-Command winget)) {
    Write-Warn "$CommandName is missing and winget is unavailable or skipped."
    return
  }
  Write-Step "Installing $PackageId with winget"
  winget install --id $PackageId --exact --silent --accept-package-agreements --accept-source-agreements
}

function Get-PythonCommand {
  if (Test-Command py) { return @("py", "-3") }
  if (Test-Command python) { return @("python") }
  throw "Python 3 is not available. Install it with winget or from python.org, then rerun this script."
}

function Invoke-Python {
  param([Parameter(ValueFromRemainingArguments = $true)][string[]]$PythonArgs)
  $cmd = Get-PythonCommand
  $exe = $cmd[0]
  $baseArgs = @()
  if ($cmd.Count -gt 1) { $baseArgs = $cmd[1..($cmd.Count - 1)] }
  $allArgs = @()
  $allArgs += $baseArgs
  $allArgs += $PythonArgs
  & $exe @allArgs
}

function Get-PythonUserBase {
  $cmd = Get-PythonCommand
  $exe = $cmd[0]
  $baseArgs = @()
  if ($cmd.Count -gt 1) { $baseArgs = $cmd[1..($cmd.Count - 1)] }
  $allArgs = @()
  $allArgs += $baseArgs
  $allArgs += @("-m", "site", "--user-base")
  $result = & $exe @allArgs
  return ($result | Select-Object -First 1)
}

function Install-BaseEnvironment {
  Write-Step "Installing base environment"
  Install-WingetPackage "git" "Git.Git"
  Install-WingetPackage "node" "OpenJS.NodeJS"
  Install-WingetPackage "python" "Python.Python.3.14"
  Install-WingetPackage "java" "EclipseAdoptium.Temurin.21.JDK"
}

function Install-ProjectDependencies {
  if ($SkipProjectDeps) { return }
  Write-Step "Installing project dependencies"
  Push-Location $RootDir
  try {
    npm install
    if (-not (Test-Path ".venv")) {
      Invoke-Python -m venv .venv
    }
    & ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
    & ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
    if ((-not (Test-Path "config.json")) -and (Test-Path "config.example.json")) {
      Copy-Item "config.example.json" "config.json"
    }
  } finally {
    Pop-Location
  }
}

function Install-PythonTools {
  Write-Step "Installing Python based tools"
  Invoke-Python -m pip install --user --upgrade semgrep ruff bandit
  $userBase = Get-PythonUserBase
  if ($userBase) {
    Add-Path (Join-Path $userBase "Scripts")
  }
}

function Install-NpmTools {
  Write-Step "Installing npm based tools"
  npm install -g eslint openapi-diff
}

function New-CmdWrapper {
  param([string]$Name, [string]$Target, [string]$Prefix = "")
  $content = "@echo off`r`n"
  if ($Prefix) {
    $content += "$Prefix `"$Target`" %*`r`n"
  } else {
    $content += "`"$Target`" %*`r`n"
  }
  Set-Content -Path (Join-Path $BinDir "$Name.cmd") -Value $content -Encoding ASCII
}

function Install-Gitleaks {
  if (Test-Command gitleaks) { return }
  Write-Step "Installing gitleaks"
  $zip = Join-Path $TempDir "gitleaks.zip"
  Invoke-Download "https://github.com/gitleaks/gitleaks/releases/download/v$GitleaksVersion/gitleaks_${GitleaksVersion}_windows_x64.zip" $zip
  $dest = Join-Path $ToolHome "gitleaks"
  Expand-Zip $zip $dest
  Copy-Item (Join-Path $dest "gitleaks.exe") (Join-Path $BinDir "gitleaks.exe") -Force
}

function Install-OsvScanner {
  if (Test-Command osv-scanner) { return }
  Write-Step "Installing osv-scanner"
  Invoke-Download "https://github.com/google/osv-scanner/releases/download/v$OsvScannerVersion/osv-scanner_windows_amd64.exe" (Join-Path $BinDir "osv-scanner.exe")
}

function Install-Trivy {
  if (Test-Command trivy) { return }
  Write-Step "Installing trivy"
  $zip = Join-Path $TempDir "trivy.zip"
  Invoke-Download "https://github.com/aquasecurity/trivy/releases/download/v$TrivyVersion/trivy_${TrivyVersion}_Windows-64bit.zip" $zip
  $dest = Join-Path $ToolHome "trivy"
  Expand-Zip $zip $dest
  Copy-Item (Join-Path $dest "trivy.exe") (Join-Path $BinDir "trivy.exe") -Force
}

function Install-Kics {
  if (Test-Command kics) { return }
  Write-Step "Installing kics"
  $zip = Join-Path $TempDir "kics.zip"
  Invoke-Download "https://github.com/Checkmarx/kics/releases/download/v$KicsVersion/kics_${KicsVersion}_windows_x64.zip" $zip
  $dest = Join-Path $ToolHome "kics"
  Expand-Zip $zip $dest
  $exe = Get-ChildItem -Path $dest -Filter "kics.exe" -Recurse | Select-Object -First 1
  if (-not $exe) { throw "kics.exe not found after extracting $zip" }
  Copy-Item $exe.FullName (Join-Path $BinDir "kics.exe") -Force
}

function Install-Pmd {
  if (Test-Command pmd) { return }
  Write-Step "Installing PMD"
  $zip = Join-Path $TempDir "pmd.zip"
  Invoke-Download "https://github.com/pmd/pmd/releases/download/pmd_releases%2F$PmdVersion/pmd-dist-$PmdVersion-bin.zip" $zip
  $dest = Join-Path $ToolHome "pmd"
  Expand-Zip $zip $dest
  $bat = Get-ChildItem -Path $dest -Filter "pmd.bat" -Recurse | Select-Object -First 1
  if (-not $bat) { throw "pmd.bat not found after extracting $zip" }
  New-CmdWrapper "pmd" $bat.FullName
}

function Install-Checkstyle {
  if (Test-Command checkstyle) { return }
  Write-Step "Installing Checkstyle"
  $dest = Join-Path $ToolHome "checkstyle"
  New-Item -ItemType Directory -Path $dest -Force | Out-Null
  $jar = Join-Path $dest "checkstyle.jar"
  Invoke-Download "https://github.com/checkstyle/checkstyle/releases/download/checkstyle-$CheckstyleVersion/checkstyle-$CheckstyleVersion-all.jar" $jar
  New-CmdWrapper "checkstyle" $jar "java -jar"
}

function Install-Spotbugs {
  if (Test-Command spotbugs) { return }
  Write-Step "Installing SpotBugs"
  $zip = Join-Path $TempDir "spotbugs.zip"
  Invoke-Download "https://github.com/spotbugs/spotbugs/releases/download/$SpotbugsVersion/spotbugs-$SpotbugsVersion.zip" $zip
  $dest = Join-Path $ToolHome "spotbugs"
  Expand-Zip $zip $dest
  $bat = Get-ChildItem -Path $dest -Filter "spotbugs.bat" -Recurse | Select-Object -First 1
  if (-not $bat) { throw "spotbugs.bat not found after extracting $zip" }
  New-CmdWrapper "spotbugs" $bat.FullName
}

function Install-DependencyCheck {
  if (Test-Command dependency-check) { return }
  Write-Step "Installing OWASP Dependency-Check"
  $zip = Join-Path $TempDir "dependency-check.zip"
  Invoke-Download "https://github.com/dependency-check/DependencyCheck/releases/download/v$DependencyCheckVersion/dependency-check-$DependencyCheckVersion-release.zip" $zip
  $dest = Join-Path $ToolHome "dependency-check"
  Expand-Zip $zip $dest
  $bat = Get-ChildItem -Path $dest -Filter "dependency-check.bat" -Recurse | Select-Object -First 1
  if (-not $bat) { throw "dependency-check.bat not found after extracting $zip" }
  New-CmdWrapper "dependency-check" $bat.FullName
}

function Install-StaticTools {
  if ($SkipStaticTools) {
    Write-Step "Skipping static toolchain installation"
    return
  }
  Write-Step "Installing static toolchain into $ToolHome"
  New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
  Add-Path $BinDir
  Install-WingetPackage "gitleaks" "Gitleaks.Gitleaks"
  Install-WingetPackage "osv-scanner" "Google.OSV-Scanner"
  Install-WingetPackage "trivy" "AquaSecurity.Trivy"
  Install-PythonTools
  Install-NpmTools
  if (-not (Test-Command gitleaks)) { Install-Gitleaks }
  if (-not (Test-Command osv-scanner)) { Install-OsvScanner }
  if (-not (Test-Command trivy)) { Install-Trivy }
  Install-Kics
  Install-Pmd
  Install-Checkstyle
  Install-Spotbugs
  Install-DependencyCheck
}

function Install-StaticRules {
  if ($SkipStaticRules) { return }
  if ($SkipProjectDeps) {
    Write-Warn "Skipping static rule sync because project dependencies were skipped."
    return
  }
  Write-Step "Syncing open-source static rules"
  Push-Location $RootDir
  try {
    npm run sync:static-rules
    npm run verify:static-rules
  } finally {
    Pop-Location
  }
}

function Test-Version {
  param([string]$Name, [string[]]$Args, [bool]$Required = $true)
  if (Test-Command $Name) {
    Write-Host ("[OK]   {0}" -f $Name)
    try { & $Name @Args | Select-Object -First 1 | ForEach-Object { Write-Host "       $_" } } catch {}
  } else {
    Write-Host ("[MISS] {0}" -f $Name) -ForegroundColor Yellow
    if ($Required) { return $false }
  }
  return $true
}

function Test-All {
  Write-Step "Verifying tool availability"
  $ok = $true
  $requireStaticTools = -not $SkipStaticTools
  $ok = (Test-Version -Name "node" -Args @("--version") -Required $true) -and $ok
  $ok = (Test-Version -Name "npm" -Args @("--version") -Required $true) -and $ok
  $ok = (Test-Version -Name "java" -Args @("-version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "semgrep" -Args @("--version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "gitleaks" -Args @("version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "ruff" -Args @("--version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "bandit" -Args @("--version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "eslint" -Args @("--version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "pmd" -Args @("--version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "checkstyle" -Args @("--version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "spotbugs" -Args @("-version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "dependency-check" -Args @("--version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "osv-scanner" -Args @("--version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "trivy" -Args @("--version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "kics" -Args @("version") -Required $requireStaticTools) -and $ok
  $ok = (Test-Version -Name "openapi-diff" -Args @("--version") -Required $requireStaticTools) -and $ok
  if ($ok) {
    Push-Location $RootDir
    try {
      node scripts/check-runtime-deps.mjs
      if ($LASTEXITCODE -ne 0) {
        $ok = $false
        Write-Warn "Runtime package dependency check failed. Run scripts\install-windows.ps1 or scripts\start-windows.ps1 -InstallIfMissing."
      }
    } catch {
      $ok = $false
      Write-Warn "Runtime package dependency check failed. Run scripts\install-windows.ps1 or scripts\start-windows.ps1 -InstallIfMissing."
    } finally {
      Pop-Location
    }
  }
  if (-not $ok) {
    throw "Some tools are missing. Reopen PowerShell so the user PATH takes effect, then rerun this script."
  }
  if (-not $requireStaticTools) {
    Write-Warn "Static tool verification was non-blocking because -SkipStaticTools was set."
  }
}

New-Item -ItemType Directory -Path $TempDir -Force | Out-Null
try {
  Add-Path $BinDir
  if (-not $VerifyOnly) {
    Install-BaseEnvironment
    Refresh-Path
    Install-ProjectDependencies
    Install-StaticTools
    Install-StaticRules
  }
  Test-All
  if ($VerifyOnly) {
    Write-Step "Verification complete."
  } else {
    Write-Step "Install complete. Run: .\scripts\start-windows.ps1"
  }
} finally {
  if (Test-Path $TempDir) {
    Remove-Item $TempDir -Recurse -Force
  }
}
