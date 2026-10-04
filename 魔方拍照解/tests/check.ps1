$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}
$originalTemp = $env:TEMP
$originalTmp = $env:TMP
$originalPythonUtf8 = $env:PYTHONUTF8
# GCC's assembler cannot write temporary files under this project's Unicode path.
$testTemp = Join-Path ([System.IO.Path]::GetTempPath()) ("cube-lens-check-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $testTemp | Out-Null
$env:TEMP = $testTemp
$env:TMP = $testTemp
$env:PYTHONUTF8 = "1"

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
    if ($LASTEXITCODE -ne 0) { throw "Recognition frontend tests failed." }
    node tests\color.test.js
    if ($LASTEXITCODE -ne 0) { throw "Color frontend tests failed." }
    node tests\two_by_two_color.test.js
    if ($LASTEXITCODE -ne 0) { throw "2x2 frontend tests failed." }
    node tests\solver_ui.test.js
    if ($LASTEXITCODE -ne 0) { throw "Solver frontend tests failed." }
    & $python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff failed with exit code $LASTEXITCODE" }
    & $python -m pytest -ra -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed with exit code $LASTEXITCODE" }
    & $python -m compileall cube_app server.py windows_launcher.py
    if ($LASTEXITCODE -ne 0) { throw "Python compilation check failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
    $env:TEMP = $originalTemp
    $env:TMP = $originalTmp
    $env:PYTHONUTF8 = $originalPythonUtf8
}
