# Launch VPN LAUNCHER (dev build) from the project venv.
# ASCII-only: PowerShell 5.1 reads files without BOM as ANSI.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $root 'venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host "venv not found: $py"
    Write-Host "Create it:  py -3 -m venv venv"
    exit 1
}
& $py (Join-Path $root 'app.py') @args
exit $LASTEXITCODE
