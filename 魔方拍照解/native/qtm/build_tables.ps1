param(
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

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$solver = Join-Path $PSScriptRoot "build\cube_solver_qtm.exe"
$cache = Join-Path $projectRoot "assets\qtm\v1"
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
if ($buildStrong -and $CiMinimal) {
    throw "QTM Strong profile cannot use -CiMinimal"
}

New-Item -ItemType Directory -Force -Path $cache | Out-Null
Push-Location $projectRoot
try {
    # The QTM service owns private copies of its HTM support PDBs.
    if (-not (Test-Path -LiteralPath (Join-Path $cache "phase1_sym_htm_v2.pdb"))) {
        & $solver build-phase1-pdb "assets\qtm\v1\phase1_sym_htm_v2.pdb" --coverage-depth 12 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "QTM support Phase-1 PDB generation failed" }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $cache "corner_htm_v2.pdb"))) {
        & $solver build-corner-pdb "assets\qtm\v1\corner_htm_v2.pdb" --coverage-depth 11 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "QTM support Corner PDB generation failed" }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $cache "tail_depth6_v4.pdb"))) {
        & $solver build-tail-pdb "assets\qtm\v1\tail_depth6_v4.pdb" --depth 6 --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "QTM support Tail-6 generation failed" }
    }
        $suffix = if ($CiMinimal) { "_depth3" } else { "" }
        $coverage = if ($CiMinimal) { 3 } else { 254 }
        & $solver build-phase1-pdb "assets\qtm\v1\phase1_qtm${suffix}_v3.pdb" --metric QTM --coverage-depth $coverage --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "QTM Phase-1 PDB generation failed" }
        & $solver build-corner-pdb "assets\qtm\v1\corner_qtm${suffix}_v3.pdb" --metric QTM --coverage-depth $coverage --threads $threads
        if ($LASTEXITCODE -ne 0) { throw "QTM Corner PDB generation failed" }
        if ($IncludeEdgePdbs) {
            & $solver build-edge-pdb "assets\qtm\v1\edge_a_qtm${suffix}_v3.pdb" --metric QTM --group 0 --coverage-depth $coverage --threads $threads
            if ($LASTEXITCODE -ne 0) { throw "First QTM edge PDB generation failed" }
            & $solver build-edge-pdb "assets\qtm\v1\edge_b_qtm${suffix}_v3.pdb" --metric QTM --group 1 --coverage-depth $coverage --threads $threads
            if ($LASTEXITCODE -ne 0) { throw "Second QTM edge PDB generation failed" }
        }
        if (-not $CiMinimal) {
            & $solver build-tail-pdb "assets\qtm\v1\tail_qtm_depth7_v5.pdb" --metric QTM --depth 7 --threads $threads
            if ($LASTEXITCODE -ne 0) { throw "QTM Tail-7 generation failed" }
        }
        if ($buildStrong) {
            $strongThreads = [Math]::Min(8, $threads)
            & $solver build-strong-pdb "assets\qtm\v1\strong_qtm_v3.pdb" --metric QTM --threads $strongThreads @resumeFlag --memory-limit-gib $MemoryLimitGiB
            if ($LASTEXITCODE -ne 0) { throw "QTM strong PDB generation failed" }
            $nibbleStrong = "assets\qtm\v1\strong_qtm_v4_nibble.pdb"
            if (-not (Test-Path -LiteralPath $nibbleStrong -PathType Leaf)) {
                & $solver convert-strong-pdb "assets\qtm\v1\strong_qtm_v3.pdb" $nibbleStrong --encoding=nibble --verify-all
                if ($LASTEXITCODE -ne 0) { throw "QTM strong PDB nibble conversion failed" }
            }
            & $solver build-tail-pdb "assets\qtm\v1\tail_qtm_depth8_v5.pdb" --metric QTM --depth 8 --threads $threads
            if ($LASTEXITCODE -ne 0) { throw "QTM Tail-8 generation failed" }
        }
        Write-Output $cache
        return
} finally {
    Pop-Location
}

Write-Output $cache
