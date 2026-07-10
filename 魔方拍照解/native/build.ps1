$ErrorActionPreference = "Stop"

$compiler = "C:\msys64\ucrt64\bin\g++.exe"
$buildDirectory = Join-Path $PSScriptRoot "build"
$target = Join-Path $buildDirectory "cube_solver.exe"

if (-not (Test-Path -LiteralPath $compiler)) {
    throw "C++ compiler not found: $compiler"
}

$env:PATH = (Split-Path -Parent $compiler) + ";" + $env:PATH
New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null

Push-Location $PSScriptRoot
try {
    & $compiler `
        -std=c++20 `
        -O3 `
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
