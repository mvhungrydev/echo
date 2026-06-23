<#
.SYNOPSIS
    Create a local development environment and install project dependencies.
.DESCRIPTION
    Creates a .venv directory at the repository root, upgrades pip, and installs
    shared layer and development requirements.
#>
[CmdletBinding()]
param(
    [switch]$Force
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot

$venvDir = Join-Path $repoRoot ".venv"
if (-Not (Test-Path $venvDir) -or $Force) {
    Write-Host "Creating virtual environment at $venvDir..."
    python -m venv $venvDir
}

$pythonExe = Join-Path $venvDir "Scripts\python.exe"
if (-Not (Test-Path $pythonExe)) {
    throw "Virtual environment Python executable not found at $pythonExe."
}

Write-Host "Upgrading pip..."
& $pythonExe -m pip install --upgrade pip

Write-Host "Installing shared and dev requirements..."
& $pythonExe -m pip install -r src/layers/shared_utils/requirements.txt -r requirements-dev.txt

Write-Host "`nDev environment is ready."
Write-Host "Activate it in the current shell with:"
Write-Host "  . .\\.venv\\Scripts\\Activate.ps1"
