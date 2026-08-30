[CmdletBinding()]
param(
    [switch]$InstallSystemDependencies,
    [switch]$SkipKiCadBuild,
    [switch]$SkipTests,
    [string]$VcpkgRoot = $env:VCPKG_ROOT,
    [string]$BuildName = "msvc-local-release",
    [int]$Jobs = [Environment]::ProcessorCount
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonRoot = Join-Path $RepoRoot "kicad-mcp-python"
$BuildDir = Join-Path $RepoRoot "build\$BuildName"
$InstallDir = Join-Path $RepoRoot "build\install\$BuildName"
$VenvDir = Join-Path $PythonRoot ".venv"

function Test-Command([string]$Name) {
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Import-MsvcEnvironment {
    if (Test-Command "cl.exe") { return }
    $VsWhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $VsWhere)) {
        throw "MSVC not found. Install the Visual Studio 2022 Build Tools Desktop development with C++ workload."
    }
    $Install = & $VsWhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if (-not $Install) { throw "Visual Studio is installed but the MSVC x64 toolchain is missing." }
    $DevCmd = Join-Path $Install "Common7\Tools\VsDevCmd.bat"
    & cmd.exe /s /c "`"$DevCmd`" -no_logo -arch=x64 && set" | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2] }
    }
}

if ($InstallSystemDependencies) {
    if (-not (Test-Command "winget.exe")) { throw "Automatic dependency installation requires winget." }
    $Packages = @(
        "Git.Git",
        "Kitware.CMake",
        "Ninja-build.Ninja",
        "Python.Python.3.13",
        "Microsoft.VisualStudio.2022.BuildTools"
    )
    foreach ($Package in $Packages) {
        $Args = @("install", "--id", $Package, "--exact", "--accept-source-agreements", "--accept-package-agreements", "--silent")
        if ($Package -eq "Microsoft.VisualStudio.2022.BuildTools") {
            $Args += @("--override", "--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended")
        }
        & winget @Args
        if ($LASTEXITCODE -notin 0, -1978335189) { throw "winget failed to install $Package." }
    }
}

if (-not $SkipKiCadBuild) {
    foreach ($Command in @("git.exe", "cmake.exe", "ninja.exe")) {
        if (-not (Test-Command $Command)) {
            throw "Missing $Command. Reopen the terminal and run scripts/bootstrap.ps1 -InstallSystemDependencies."
        }
    }
    Import-MsvcEnvironment

    if (-not $VcpkgRoot) { $VcpkgRoot = Join-Path $env:USERPROFILE "vcpkg" }
    if (-not (Test-Path (Join-Path $VcpkgRoot ".git"))) {
        git clone https://github.com/microsoft/vcpkg.git $VcpkgRoot
    }
    $BootstrapVcpkg = Join-Path $VcpkgRoot "bootstrap-vcpkg.bat"
    & $BootstrapVcpkg -disableMetrics
    if ($LASTEXITCODE -ne 0) { throw "vcpkg bootstrap failed." }
    $env:VCPKG_ROOT = $VcpkgRoot
}

$PythonCommand = if (Test-Command "py.exe") { "py.exe" } elseif (Test-Command "python.exe") { "python.exe" } else { throw "Python 3.10+ is missing." }
$PythonArgs = if ($PythonCommand -eq "py.exe") { @("-3") } else { @() }
if (-not (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) {
    & $PythonCommand @PythonArgs -m venv $VenvDir
}
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e "$PythonRoot[dev]"

if (-not $SkipKiCadBuild) {
    cmake -S $RepoRoot -B $BuildDir -G Ninja `
        "-DCMAKE_BUILD_TYPE=Release" `
        "-DCMAKE_INSTALL_PREFIX=$InstallDir" `
        "-DCMAKE_TOOLCHAIN_FILE=$(Join-Path $VcpkgRoot 'scripts\buildsystems\vcpkg.cmake')" `
        "-DKICAD_BUILD_QA_TESTS=OFF" `
        "-DKICAD_SCRIPTING_WXPYTHON=OFF" `
        "-DKICAD_WIN32_DPI_AWARE=ON"
    if ($LASTEXITCODE -ne 0) { throw "KiCad CMake configuration failed." }
    cmake --build $BuildDir --target install --parallel $Jobs
    if ($LASTEXITCODE -ne 0) { throw "KiCad build failed." }
}

$KicadCli = Join-Path $InstallDir "bin\kicad-cli.exe"
$Eeschema = Join-Path $InstallDir "bin\eeschema.exe"
$StockData = Join-Path $InstallDir "share\kicad"
foreach ($Path in @($KicadCli, $Eeschema, $StockData)) {
    if (-not (Test-Path $Path)) { throw "Incomplete repository runtime; missing: $Path" }
}

if (-not $SkipTests) {
    $Tests = @(
        "tests/test_project.py", "tests/test_runtime.py", "tests/test_reload_gate.py",
        "tests/test_mcp_stdio.py", "tests/test_geometry.py", "tests/test_constraint_layout.py",
        "tests/test_label_placement.py", "tests/test_pathfinding.py",
        "tests/test_svg_metrics.py", "tests/test_draw_report.py"
    )
    Push-Location $PythonRoot
    try { & $VenvPython -m pytest @Tests -q } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "MCP core tests failed." }
}

$ConfigDir = Join-Path $RepoRoot "build\mcp-config"
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
$Environment = @{ KICAD_CLI = $KicadCli; KICAD_STOCK_DATA_HOME = $StockData }
$VsCode = @{ servers = @{ kicad = @{ type = "stdio"; command = $VenvPython; args = @("-m", "kicad_mcp"); env = $Environment } } }
$Claude = @{ mcpServers = @{ kicad = @{ command = $VenvPython; args = @("-m", "kicad_mcp"); env = $Environment } } }
$VsCode | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $ConfigDir "vscode-mcp.json")
$Claude | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $ConfigDir "claude-mcp.json")

Write-Host "Bootstrap complete"
Write-Host "  KiCad CLI: $KicadCli"
Write-Host "  Eeschema:   $Eeschema"
Write-Host "  MCP Python: $VenvPython"
Write-Host "  Config:     $ConfigDir"
Write-Host "Next: & '$Eeschema' '<project>.kicad_sch'"
