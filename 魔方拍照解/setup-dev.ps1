param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venvPython = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    Write-Host "Creating .venv with $Python"
    & $Python -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed with exit code $LASTEXITCODE" }
}

Push-Location $root
try {
    & $venvPython -m pip install "pip==26.1.2"
    if ($LASTEXITCODE -ne 0) { throw "Pinned pip installation failed with exit code $LASTEXITCODE" }
    & $venvPython -m pip install -r requirements-dev.txt
    if ($LASTEXITCODE -ne 0) { throw "Development dependency installation failed with exit code $LASTEXITCODE" }
    & $venvPython -m pip install --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw "Editable project installation failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}

Write-Host "Development environment is ready. Run .\tests\check.ps1"
