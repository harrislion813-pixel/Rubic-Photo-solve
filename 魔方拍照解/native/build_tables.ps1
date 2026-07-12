param(
    [switch]$IncludeEdgePdbs,
    [switch]$CiMinimal,
    [string]$Compiler
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$solver = Join-Path $PSScriptRoot "build\cube_solver.exe"
$cache = Join-Path $projectRoot ".cache\native"
$threads = [Math]::Min(32, [Math]::Max(1, [Environment]::ProcessorCount - 1))

if (-not (Test-Path -LiteralPath $solver)) {
    & (Join-Path $PSScriptRoot "build.ps1") -Compiler $Compiler | Out-Null
}

if ($CiMinimal -and $IncludeEdgePdbs) {
    throw "-CiMinimal cannot be combined with -IncludeEdgePdbs"
}

New-Item -ItemType Directory -Force -Path $cache | Out-Null
Push-Location $projectRoot
try {
    & $solver build-phase1-pdb ".cache\native\phase1_sym_htm_v2.pdb" --coverage-depth 12 --threads $threads
    if ($LASTEXITCODE -ne 0) { throw "Phase-1 symmetry PDB generation failed" }
    & $solver build-corner-pdb ".cache\native\corner_htm_v2.pdb" --coverage-depth 11 --threads $threads
    if ($LASTEXITCODE -ne 0) { throw "Corner PDB generation failed" }
    if ($IncludeEdgePdbs) {
        & $solver build-edge-pdb ".cache\native\edge_a_htm_v2.pdb" --first-edge 0 --coverage-depth 10 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "First edge PDB generation failed" }
        & $solver build-edge-pdb ".cache\native\edge_b_htm_v2.pdb" --first-edge 6 --coverage-depth 10 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "Second edge PDB generation failed" }
        & $solver build-edge-pdb ".cache\native\edge_c_htm_v2.pdb" --group 2 --coverage-depth 10 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "Third edge PDB generation failed" }
        & $solver build-edge-pdb ".cache\native\edge_d_htm_v2.pdb" --group 3 --coverage-depth 10 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "Fourth edge PDB generation failed" }
        & $solver build-edge-pdb ".cache\native\edge_e_htm_v2.pdb" --group 4 --coverage-depth 10 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "Fifth edge PDB generation failed" }
        & $solver build-edge-pdb ".cache\native\edge_f_htm_v2.pdb" --group 5 --coverage-depth 10 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "Sixth edge PDB generation failed" }
        & $solver build-edge-pdb ".cache\native\edge_g_htm_v2.pdb" --group 6 --coverage-depth 10 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "Seventh edge PDB generation failed" }
        & $solver build-edge-pdb ".cache\native\edge_h_htm_v2.pdb" --group 7 --coverage-depth 10 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "Eighth edge PDB generation failed" }
    }
    if (-not $CiMinimal) {
        & $solver build-tail-pdb ".cache\native\tail_depth6_v4.pdb" --depth 6 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "Tail database generation failed" }
    }
} finally {
    Pop-Location
}

Write-Output $cache
