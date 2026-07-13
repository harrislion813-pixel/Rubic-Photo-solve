param(
    [string]$Python = "",
    [switch]$SkipTests,
    [switch]$SkipBuild,
    [switch]$IncludeTailPdb,
    [switch]$CreateTag,
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$repositoryRoot = Split-Path -Parent $projectRoot
if (-not $Python) {
    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    $Python = if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $venvPython } else { "python" }
}

Push-Location $projectRoot
try {
    $version = (& $Python release\check_version.py).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $version) { throw "Version validation failed." }
    $tag = "v$version"

    $dirty = @(git -C $repositoryRoot status --porcelain --untracked-files=all)
    if ($dirty.Count -gt 0 -and -not $AllowDirty) {
        throw "Release preparation requires a clean worktree. Commit or stash changes first."
    }
    if ($CreateTag -and $AllowDirty) {
        throw "-CreateTag cannot be combined with -AllowDirty."
    }

    if (-not $SkipTests) {
        & (Join-Path $projectRoot "tests\check.ps1")
        if ($LASTEXITCODE -ne 0) { throw "Release tests failed with exit code $LASTEXITCODE" }
    }

    if (-not $SkipBuild) {
        & (Join-Path $PSScriptRoot "build_windows.ps1") -Python $Python -IncludeTailPdb:$IncludeTailPdb
        if ($LASTEXITCODE -ne 0) { throw "Windows release build failed with exit code $LASTEXITCODE" }
        $archive = Join-Path $projectRoot "dist\RubicPhotoSolve-$version-windows-x64.zip"
        if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) { throw "Expected release archive is missing: $archive" }
        $hash = Get-FileHash -LiteralPath $archive -Algorithm SHA256
        Write-Host "Release archive: $archive"
        Write-Host "SHA256: $($hash.Hash)"
    }

    if ($CreateTag) {
        if (git -C $repositoryRoot tag --list $tag) { throw "Git tag already exists: $tag" }
        git -C $repositoryRoot tag -a $tag -m "Cube Lens $tag"
        if ($LASTEXITCODE -ne 0) { throw "Git tag creation failed with exit code $LASTEXITCODE" }
        Write-Host "Created tag $tag. Push it with: git push origin $tag"
    } else {
        Write-Host "Release $version is ready for review. After committing, run:"
        Write-Host ".\release\prepare_release.ps1 -CreateTag"
        Write-Host "git push origin $tag"
    }
} finally {
    Pop-Location
}
