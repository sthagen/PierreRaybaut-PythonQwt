# Run the load-test benchmark in one of the local venvs.
#
# Usage:
#   .\scripts\bench_qt.ps1                # run all three bindings
#   .\scripts\bench_qt.ps1 pyqt5          # run a single binding
#   .\scripts\bench_qt.ps1 pyqt5,pyside6  # run a subset
#   .\scripts\bench_qt.ps1 -Repeat 3      # repeat each run N times
#
# The script sets PYTHONQWT_UNATTENDED_TESTS=1 and invokes
# qwt/tests/test_loadtest.py via the binding-specific venv. The script
# captures the "Average elapsed time" line printed by the benchmark.

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string[]] $Bindings = @("pyqt5", "pyqt6", "pyside6"),
    [int] $Repeat = 1
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    foreach ($binding in $Bindings) {
        $py = Join-Path $repoRoot ".venvs\$binding\Scripts\python.exe"
        if (-not (Test-Path $py)) {
            Write-Warning "Skipping $binding (venv not found at $py)"
            continue
        }
        $env:PYTHONQWT_UNATTENDED_TESTS = "1"
        $env:QT_API = $binding
        for ($i = 1; $i -le $Repeat; $i++) {
            $output = & $py "qwt\tests\test_loadtest.py" 2>&1
            $avg = $output | Select-String -Pattern "Average elapsed time" | Select-Object -Last 1
            $tag = "[{0}]" -f $binding
            if ($Repeat -gt 1) { $tag = "{0} run {1}/{2}" -f $tag, $i, $Repeat }
            if ($avg) {
                Write-Host ("{0} {1}" -f $tag, $avg.Line.Trim())
            }
            else {
                Write-Host ("{0} (no result)" -f $tag)
                Write-Host ($output -join [Environment]::NewLine)
            }
        }
        Remove-Item Env:PYTHONQWT_UNATTENDED_TESTS -ErrorAction SilentlyContinue
        Remove-Item Env:QT_API -ErrorAction SilentlyContinue
    }
}
finally {
    Pop-Location
}
