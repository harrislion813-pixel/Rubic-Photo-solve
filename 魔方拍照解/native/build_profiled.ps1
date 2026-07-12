param(
    [string]$Compiler = "C:\msys64\ucrt64\bin\g++.exe"
)

$ErrorActionPreference = "Stop"

$compiler = $Compiler
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildDirectory = Join-Path $PSScriptRoot "build"
$trainingTarget = Join-Path $buildDirectory "cube_solver_profiled.exe"
$target = Join-Path $buildDirectory "cube_solver.exe"
$profileName = "pgo-$PID"
$profileDirectory = Join-Path (Join-Path $projectRoot ".cache\native") $profileName
$profileFromProject = ".cache/native/$profileName"
$profileFromNative = "../.cache/native/$profileName"

$cornerPdb = Join-Path $projectRoot ".cache\native\corner_htm_v2.pdb"
$phase1Pdb = Join-Path $projectRoot ".cache\native\phase1_sym_htm_v2.pdb"
$tailPdb = Join-Path $projectRoot ".cache\native\tail_depth6_v4.pdb"
foreach ($path in @($cornerPdb, $phase1Pdb, $tailPdb)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Profile-guided build requires the native databases: $path"
    }
}
if (-not (Test-Path -LiteralPath $compiler)) {
    throw "C++ compiler not found: $compiler"
}

$env:PATH = (Split-Path -Parent $compiler) + ";" + $env:PATH
New-Item -ItemType Directory -Force -Path $buildDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $profileDirectory | Out-Null

$common = @(
    "-std=c++20",
    "-O3",
    "-march=native",
    "-mtune=native",
    "-flto",
    "-DNDEBUG",
    "-Wall",
    "-Wextra",
    "-Wpedantic",
    "-I", "include",
    "src\cube.cpp",
    "src\pdb.cpp",
    "src\solver.cpp",
    "src\symmetry.cpp",
    "src\tail.cpp",
    "src\main.cpp",
    "-pthread",
    "-static"
)

Push-Location $PSScriptRoot
try {
    $prefix = (Get-Location).Path
    & $compiler @common "-fprofile-generate=$profileFromProject" "-fprofile-prefix-path=$prefix" `
        -o "build\cube_solver_profiled.exe"
    if ($LASTEXITCODE -ne 0) { throw "PGO instrumented build failed with exit code $LASTEXITCODE" }

    Push-Location $projectRoot
    try {
        $ErrorActionPreference = "Continue"
        try {
            & $trainingTarget solve `
                "RFLLURLRRDFULRRBDLUBFUFULDRDLDRDBFFDUBFULFRUBBLBDBBFDU" `
                --max-depth 16 `
                --timeout 120 `
                --threads ([Environment]::ProcessorCount) `
                --pdb ".cache/native/corner_htm_v2.pdb" `
                --phase1-pdb ".cache/native/phase1_sym_htm_v2.pdb" `
                --tail-pdb ".cache/native/tail_depth6_v4.pdb" `
                --incumbent "D L' D F2 D2 L' U' R U2 F2 L F' U2 L U B" 2>$null | Out-Null
            $trainingExitCode = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = "Stop"
        }
        if ($trainingExitCode -ne 0) { throw "PGO training solve failed with exit code $trainingExitCode" }
    } finally {
        Pop-Location
    }

    & $compiler @common "-fprofile-use=$profileFromNative" -fprofile-correction `
        "-fprofile-prefix-path=$prefix" -o "build\cube_solver_profiled.exe"
    if ($LASTEXITCODE -ne 0) { throw "PGO optimized build failed with exit code $LASTEXITCODE" }
    Move-Item -LiteralPath $trainingTarget -Destination $target -Force
} finally {
    Pop-Location
    $resolvedProfile = [System.IO.Path]::GetFullPath($profileDirectory)
    $resolvedCache = [System.IO.Path]::GetFullPath((Join-Path $projectRoot ".cache\native"))
    if ($resolvedProfile.StartsWith($resolvedCache, [System.StringComparison]::OrdinalIgnoreCase) -and
        ([System.IO.Path]::GetFileName($resolvedProfile)).StartsWith("pgo-")) {
        Remove-Item -LiteralPath $resolvedProfile -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Output $target
