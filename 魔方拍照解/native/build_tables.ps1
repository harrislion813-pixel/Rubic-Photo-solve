param(
    [ValidateSet("HTM", "QTM")][string]$Metric = "HTM",
    [ValidateSet("Standard", "Strong")][string]$Profile = "Standard",
    [switch]$IncludeEdgePdbs,
    [switch]$Strong,
    [switch]$Resume = $true,
    [switch]$CiMinimal,
    [double]$MemoryLimitGiB = 12,
    [int]$Parallelism = 0,
    [string]$Compiler
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$solver = Join-Path $PSScriptRoot "build\cube_solver.exe"
$cache = Join-Path $projectRoot ".cache\native"
$threads = if ($Parallelism -gt 0) { $Parallelism } else {
    [Math]::Min(32, [Math]::Max(1, [Environment]::ProcessorCount - 1))
}
$buildStrong = $Strong -or $Profile -eq "Strong"
$resumeFlag = if ($Resume) { @("--resume") } else { @() }

if ($Parallelism -lt 0 -or $threads -lt 1 -or $threads -gt 32 -or $MemoryLimitGiB -le 0) {
    throw "Parallelism must be 1..32 and MemoryLimitGiB must be positive."
}

if (-not (Test-Path -LiteralPath $solver)) {
    & (Join-Path $PSScriptRoot "build.ps1") -Compiler $Compiler | Out-Null
}

if ($CiMinimal -and $IncludeEdgePdbs) {
    throw "-CiMinimal cannot be combined with -IncludeEdgePdbs"
}
if ($buildStrong -and ($Metric -ne "QTM" -or $CiMinimal)) {
    throw "QTM Strong profile requires -Metric QTM without -CiMinimal"
}

New-Item -ItemType Directory -Force -Path $cache | Out-Null
Push-Location $projectRoot
try {
    if ($Metric -eq "QTM") {
        $suffix = if ($CiMinimal) { "_depth3" } else { "" }
        $coverage = if ($CiMinimal) { 3 } else { 254 }
        & $solver build-phase1-pdb ".cache\native\phase1_qtm${suffix}_v3.pdb" --metric QTM --coverage-depth $coverage --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "QTM Phase-1 PDB generation failed" }
        & $solver build-corner-pdb ".cache\native\corner_qtm${suffix}_v3.pdb" --metric QTM --coverage-depth $coverage --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "QTM Corner PDB generation failed" }
        if ($IncludeEdgePdbs) {
            & $solver build-edge-pdb ".cache\native\edge_a_qtm${suffix}_v3.pdb" --metric QTM --group 0 --coverage-depth $coverage --threads $threads
            if ($LASTEXITCODE -ne 0) { throw "First QTM edge PDB generation failed" }
            & $solver build-edge-pdb ".cache\native\edge_b_qtm${suffix}_v3.pdb" --metric QTM --group 1 --coverage-depth $coverage --threads $threads
            if ($LASTEXITCODE -ne 0) { throw "Second QTM edge PDB generation failed" }
        }
        if (-not $CiMinimal) {
            & $solver build-tail-pdb ".cache\native\tail_qtm_depth7_v5.pdb" --metric QTM --depth 7 --threads $threads
            if ($LASTEXITCODE -ne 0) { throw "QTM Tail-7 generation failed" }
        }
        if ($buildStrong) {
            $strongThreads = [Math]::Min(8, $threads)
            & $solver build-strong-pdb ".cache\native\strong_qtm_v3.pdb" --metric QTM --threads $strongThreads @resumeFlag --memory-limit-gib $MemoryLimitGiB
            if ($LASTEXITCODE -ne 0) { throw "QTM strong PDB generation failed" }
            & $solver build-tail-pdb ".cache\native\tail_qtm_depth8_v5.pdb" --metric QTM --depth 8 --threads $threads
            if ($LASTEXITCODE -ne 0) { throw "QTM Tail-8 generation failed" }
        }
        Write-Output $cache
        return
    }
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
