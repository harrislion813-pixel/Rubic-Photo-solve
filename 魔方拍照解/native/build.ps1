param(
    [switch]$ProfileGuided,
    [switch]$Portable,
    [string]$Compiler
)

$ErrorActionPreference = "Stop"

$buildDirectory = Join-Path $PSScriptRoot "build"
$target = Join-Path $buildDirectory "cube_solver.exe"

function Resolve-CompilerPath {
    param([string]$RequestedCompiler)

    $candidates = @()
    if ($RequestedCompiler) { $candidates += $RequestedCompiler }
    if ($env:CXX) { $candidates += $env:CXX }
    $candidates += "g++.exe", "g++", "C:\msys64\ucrt64\bin\g++.exe"

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
        $command = Get-Command $candidate -CommandType Application -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    throw "C++ compiler not found. Pass -Compiler, set CXX, or add g++ to PATH."
}

$compilerPath = Resolve-CompilerPath $Compiler

if ($ProfileGuided) {
    & (Join-Path $PSScriptRoot "build_profiled.ps1") -Compiler $compilerPath
    if ($LASTEXITCODE -ne 0) {
        throw "Profile-guided native solver build failed with exit code $LASTEXITCODE"
    }
    return
}

$env:PATH = (Split-Path -Parent $compilerPath) + ";" + $env:PATH
New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null
Write-Host "Using C++ compiler: $compilerPath"
$architectureFlags = if ($Portable) { @("-march=x86-64", "-mtune=generic") } else { @("-march=native", "-mtune=native") }

Push-Location $PSScriptRoot
try {
    & $compilerPath `
        -std=c++20 `
        -O3 `
        @architectureFlags `
        -flto `
        -DNDEBUG `
        -Wall `
        -Wextra `
        -Wpedantic `
        -I include `
        src\cube.cpp `
        src\fast.cpp `
        src\pdb.cpp `
        src\solver.cpp `
        src\symmetry.cpp `
        src\strong_coords.cpp `
        src\strong_pdb.cpp `
        src\tail.cpp `
        src\main.cpp `
        -pthread `
        -static `
        -municode `
        -o build\cube_solver.exe
} finally {
    Pop-Location
}

if ($LASTEXITCODE -ne 0) {
    throw "Native solver build failed with exit code $LASTEXITCODE"
}

$buildInfo = [ordered]@{
    compiler = (& $compilerPath --version | Select-Object -First 1)
    flags = "-std=c++20 -O3 $($architectureFlags -join ' ') -flto -DNDEBUG -Wall -Wextra -Wpedantic -pthread -static -municode"
    portable = [bool]$Portable
    profile_guided = $false
    built_at = [DateTime]::UtcNow.ToString("o")
    binary_sha256 = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash
    source_sha256 = @{}
}
Get-ChildItem (Join-Path $PSScriptRoot "src"), (Join-Path $PSScriptRoot "include") -File -Recurse | ForEach-Object {
    $buildInfo.source_sha256[$_.Name] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
}
$buildInfo | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $buildDirectory "build-info.json") -Encoding utf8

Write-Output $target
