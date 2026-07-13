$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}
$originalTemp = $env:TEMP
$originalTmp = $env:TMP
$testTemp = Join-Path $root ".cache\test-tmp"
New-Item -ItemType Directory -Force -Path $testTemp | Out-Null
$env:TEMP = $testTemp
$env:TMP = $testTemp

Push-Location $root
try {
    & $python -c "import pytest, pytest_cov, ruff"
    if ($LASTEXITCODE -ne 0) {
        throw "Development dependencies are missing. Run .\setup-dev.ps1 first."
    }
    if (-not (Get-Command node -CommandType Application -ErrorAction SilentlyContinue)) {
        throw "Node.js is required for frontend tests. Install Node.js 20 or newer."
    }
    & $python release\check_version.py
    if ($LASTEXITCODE -ne 0) { throw "Version consistency check failed with exit code $LASTEXITCODE" }
    node tests\recognition.test.js
    node tests\color.test.js
    node tests\two_by_two_color.test.js
    node tests\solver_ui.test.js
    & $python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff failed with exit code $LASTEXITCODE" }
    & $python -m pytest -ra
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed with exit code $LASTEXITCODE" }
    & $python -m compileall cube_app server.py windows_launcher.py
    if ($LASTEXITCODE -ne 0) { throw "Python compilation check failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
    $env:TEMP = $originalTemp
    $env:TMP = $originalTmp
}
