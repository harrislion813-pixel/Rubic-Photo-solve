$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    node tests\recognition.test.js
    node tests\color.test.js
    node tests\two_by_two_color.test.js
    node tests\solver_ui.test.js
    python -m unittest discover -s tests -v
    python -m compileall cube_app server.py
} finally {
    Pop-Location
}
