param(
    [switch]$ProfileGuided,
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

Push-Location $PSScriptRoot
try {
    & $compilerPath `
        -std=c++20 `
        -O3 `
        -march=native `
        -mtune=native `
        -flto `
        -DNDEBUG `
        -Wall `
        -Wextra `
        -Wpedantic `
        -I include `
        src\cube.cpp `
        src\pdb.cpp `
        src\solver.cpp `
        src\symmetry.cpp `
        src\tail.cpp `
        src\main.cpp `
        -pthread `
        -static `
        -o build\cube_solver.exe
} finally {
    Pop-Location
}

if ($LASTEXITCODE -ne 0) {
    throw "Native solver build failed with exit code $LASTEXITCODE"
}

Write-Output $target
