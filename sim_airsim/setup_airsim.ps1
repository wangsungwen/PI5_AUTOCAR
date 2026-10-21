# RPI5_AutoCAR x AirSim one-shot setup (Windows PowerShell)
# Run from the project root:
#   powershell -ExecutionPolicy Bypass -File sim_airsim\setup_airsim.ps1
#   powershell -ExecutionPolicy Bypass -File sim_airsim\setup_airsim.ps1 -DownloadEnv AirSimNH
param(
    [string]$Venv = ".venv",
    [string]$DownloadEnv = "",          # AirSimNH | Blocks | LandscapeMountains | Africa ... (CityEnviron is split in 2 parts: download manually)
    [string]$EnvDir = "C:\AirSimEnvs"
)
$ErrorActionPreference = "Continue"   # native tools write warnings to stderr; we check $LASTEXITCODE instead
function Check($msg) { if ($LASTEXITCODE -ne 0) { Write-Error "FAILED: $msg"; exit 1 } }
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# 1. Python venv (reuse the project's .venv that already has ultralytics/torch)
if (-not (Test-Path "$Venv\Scripts\python.exe")) {
    Write-Host "[1/4] creating venv $Venv"
    py -3.11 -m venv $Venv
}
$Py = Join-Path $Root "$Venv\Scripts\python.exe"
Write-Host "[1/4] python: $Py"

# 2. AirSim client (order matters)
Write-Host "[2/4] installing AirSim Python client"
& $Py -m pip install --upgrade pip
& $Py -m pip install numpy setuptools wheel "msgpack-rpc-python==0.4.1"; Check "msgpack-rpc-python"
& $Py -m pip install --no-deps --no-build-isolation "airsim==1.8.1"; Check "airsim"
& $Py -c "import ultralytics" *> $null
if ($LASTEXITCODE -ne 0) { & $Py -m pip install -r requirements-autonomy.txt; Check "requirements-autonomy" }
& $Py -c "import airsim, cv2, ultralytics; print('airsim', airsim.__version__, '| cv2', cv2.__version__, '| ultralytics', ultralytics.__version__)"; Check "import test"

# 3. settings.json -> %USERPROFILE%\Documents\AirSim\settings.json (backup old one)
$Docs = [Environment]::GetFolderPath("MyDocuments")
$Target = Join-Path $Docs "AirSim"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
$Dest = Join-Path $Target "settings.json"
if (Test-Path $Dest) {
    $Backup = "$Dest.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Copy-Item $Dest $Backup
    Write-Host "[3/4] backed up existing settings -> $Backup"
}
Copy-Item "sim_airsim\settings.json" $Dest -Force
Write-Host "[3/4] settings.json -> $Dest"

# 4. optional: download a prebuilt environment from the v1.8.1 Windows release
if ($DownloadEnv) {
    New-Item -ItemType Directory -Force -Path $EnvDir | Out-Null
    $Base = "https://github.com/microsoft/AirSim/releases/download/v1.8.1-windows"
    $Zip = Join-Path $EnvDir "$DownloadEnv.zip"
    Write-Host "[4/4] downloading $DownloadEnv (several GB, be patient)"
    $ProgressPreference = "SilentlyContinue"   # makes Invoke-WebRequest much faster
    Invoke-WebRequest "$Base/$DownloadEnv.zip" -OutFile $Zip; if (-not $?) { exit 1 }
    Expand-Archive $Zip -DestinationPath $EnvDir -Force
    Write-Host "[4/4] extracted to $EnvDir\$DownloadEnv  -> double-click run.bat (or the .exe) inside it"
} else {
    Write-Host "[4/4] skipped env download (use -DownloadEnv AirSimNH)"
}
Write-Host "`nNext: start the AirSim environment, then:"
Write-Host "  $Py -m sim_airsim.check_airsim"
Write-Host "  $Py -m sim_airsim.run_autopilot --show"
