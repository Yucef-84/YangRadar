$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "YangRadar install started..."

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  throw "Python was not found. Install Python 3.11 or newer, then open PowerShell again."
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
  throw "Node.js was not found. Install Node.js 20 or newer, then open PowerShell again."
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
  throw "npm was not found. Install Node.js 20 or newer, then open PowerShell again."
}

if (-not (Test-Path ".venv")) {
  python -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
& npm.cmd install --prefix frontend

Write-Host ""
Write-Host "Install complete."
Write-Host "Next: powershell -ExecutionPolicy Bypass -File .\scripts\start-yangradar.ps1"
