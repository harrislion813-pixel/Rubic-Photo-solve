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
    & $venvPython -X utf8 tests\check_environment.py --output artifacts\maintenance\environment.json
    if ($LASTEXITCODE -ne 0) { throw "Development environment verification failed." }
    npm ci --ignore-scripts --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "Locked browser dependencies could not be installed. Node.js 20 or newer is required." }
    npx playwright install chromium
    if ($LASTEXITCODE -ne 0) { throw "Chromium installation failed." }
} finally {
    Pop-Location
}

Write-Host "Development environment is ready. Run .\tests\check.ps1"
