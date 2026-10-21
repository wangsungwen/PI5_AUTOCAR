param(
    [string]$EngineRoot = "",
    [switch]$Prepare,
    [switch]$Game
)
$ErrorActionPreference = "Stop"
$Project = Join-Path $PSScriptRoot "RoadScenes.uproject"
if (-not $EngineRoot) {
    $Candidates = @(
        "C:\Program Files\Epic Games\UE_4.27",
        "D:\Epic Games\UE_4.27",
        "D:\UE_4.27"
    )
    $Registry = Get-ItemProperty "HKLM:\SOFTWARE\EpicGames\Unreal Engine\4.27" -ErrorAction SilentlyContinue
    if ($Registry.InstalledDirectory) { $Candidates = @($Registry.InstalledDirectory) + $Candidates }
    $EngineRoot = $Candidates | Where-Object {
        Test-Path -LiteralPath (Join-Path $_ "Engine\Binaries\Win64\UE4Editor.exe")
    } | Select-Object -First 1
}
if (-not $EngineRoot) {
    throw "UE4.27 Editor not found. Install UE4.27 + Visual Studio C++ tools, then pass -EngineRoot. AirSimNH.exe is a packaged game and cannot compile this project."
}
$Editor = Join-Path $EngineRoot "Engine\Binaries\Win64\UE4Editor.exe"
$Build = Join-Path $EngineRoot "Engine\Build\BatchFiles\Build.bat"
if (-not (Test-Path -LiteralPath $Editor)) { throw "Invalid EngineRoot: $EngineRoot" }
if ($Prepare) {
    & $Build RoadScenesEditor Win64 Development $Project -WaitMutex
    if ($LASTEXITCODE -ne 0) { throw "UE4 build failed. Check the C++ toolchain and build log." }
    $Script = Join-Path $PSScriptRoot "tools\prepare_editor.py"
    & $Editor $Project "-ExecutePythonScript=$Script" -unattended -nosplash
    if ($LASTEXITCODE -ne 0) { throw "Editor asset preparation failed." }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot "Content\Maps\Indoor.umap"))) {
        throw "Indoor.umap was not created. Inspect Saved\Logs."
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot "Content\Maps\Indoor.umap"))) {
    throw "Run launch.ps1 -Prepare once to build the module and create materials/map."
}
$EditorArgs = @("`"$Project`"", "/Game/Maps/Indoor")
if ($Game) { $EditorArgs += @("-game", "-windowed", "-ResX=1280", "-ResY=720") }
Start-Process -FilePath $Editor -ArgumentList $EditorArgs -WindowStyle Normal
