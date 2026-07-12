$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

Push-Location $root
try {
    node tests\recognition.test.js
    node tests\color.test.js
    node tests\two_by_two_color.test.js
    node tests\solver_ui.test.js
    & $python -m pytest -ra
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed with exit code $LASTEXITCODE" }
    & $python -m compileall cube_app server.py
    if ($LASTEXITCODE -ne 0) { throw "Python compilation check failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
