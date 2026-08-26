param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $Root ".runtime"
$BackendUrl = "http://127.0.0.1:8001/api/health"
$FrontendUrl = "http://127.0.0.1:4173"

Set-Location $Root

function Test-HttpEndpoint {
  param([string]$Uri)

  try {
    $Response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
    return $Response.StatusCode -ge 200 -and $Response.StatusCode -lt 500
  } catch {
    return $false
  }
}

function Wait-HttpEndpoint {
  param(
    [string]$Uri,
    [int]$TimeoutSeconds
  )

  $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
  while ((Get-Date) -lt $Deadline) {
    if (Test-HttpEndpoint -Uri $Uri) {
      return $true
    }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Assert-PortAvailable {
  param([int]$Port)

  $Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($Listener) {
    $Owner = Get-Process -Id $Listener.OwningProcess -ErrorAction SilentlyContinue
    $OwnerName = if ($Owner) { $Owner.ProcessName } else { "PID $($Listener.OwningProcess)" }
    throw "Port $Port is already being used by $OwnerName. Close that program and try again."
  }
}

function Get-ListenerProcessId {
  param([int]$Port)

  $Listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
  if ($Listener) {
    return $Listener.OwningProcess
  }
  return $null
}

function Show-StartupError {
  param(
    [string]$Message,
    [string]$LogPath
  )

  Write-Host ""
  Write-Host $Message -ForegroundColor Red
  if (Test-Path $LogPath) {
    Write-Host ""
    Write-Host "Recent log output:" -ForegroundColor Yellow
    Get-Content $LogPath -Tail 20
  }
  throw "YangRadar could not start."
}

Write-Host "Starting YangRadar..." -ForegroundColor Cyan

if (-not (Test-Path ".venv\Scripts\python.exe") -or -not (Test-Path "frontend\node_modules")) {
  Write-Host "First run detected. Installing required packages..." -ForegroundColor Yellow
  & (Join-Path $PSScriptRoot "install.ps1")
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
  throw "npm was not found. Install Node.js 20 or newer, then try again."
}

New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

$BackendOutLog = Join-Path $RuntimeDir "backend.log"
$BackendErrorLog = Join-Path $RuntimeDir "backend-error.log"
$FrontendOutLog = Join-Path $RuntimeDir "frontend.log"
$FrontendErrorLog = Join-Path $RuntimeDir "frontend-error.log"

if (Test-HttpEndpoint -Uri $BackendUrl) {
  Write-Host "Backend is already running."
} else {
  Assert-PortAvailable -Port 8001
  $BackendProcess = Start-Process `
    -FilePath (Join-Path $Root ".venv\Scripts\python.exe") `
    -ArgumentList @("-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8001") `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $BackendOutLog `
    -RedirectStandardError $BackendErrorLog `
    -WindowStyle Hidden `
    -PassThru
  if (-not (Wait-HttpEndpoint -Uri $BackendUrl -TimeoutSeconds 45)) {
    Show-StartupError -Message "Backend did not become ready." -LogPath $BackendErrorLog
  }
  $BackendListenerProcessId = Get-ListenerProcessId -Port 8001
  if ($BackendListenerProcessId) {
    Set-Content -Path (Join-Path $RuntimeDir "backend.pid") -Value $BackendListenerProcessId
  }
  Write-Host "Backend is ready."
}

if (Test-HttpEndpoint -Uri $FrontendUrl) {
  Write-Host "Frontend is already running."
} else {
  Assert-PortAvailable -Port 4173
  $FrontendProcess = Start-Process `
    -FilePath "cmd.exe" `
    -ArgumentList @("/d", "/s", "/c", "npm.cmd run dev --prefix frontend") `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $FrontendOutLog `
    -RedirectStandardError $FrontendErrorLog `
    -WindowStyle Hidden `
    -PassThru
  if (-not (Wait-HttpEndpoint -Uri $FrontendUrl -TimeoutSeconds 45)) {
    Show-StartupError -Message "Frontend did not become ready." -LogPath $FrontendErrorLog
  }
  $FrontendListenerProcessId = Get-ListenerProcessId -Port 4173
  if ($FrontendListenerProcessId) {
    Set-Content -Path (Join-Path $RuntimeDir "frontend.pid") -Value $FrontendListenerProcessId
  }
  Write-Host "Frontend is ready."
}

if (-not $NoBrowser) {
  Start-Process $FrontendUrl
}
Write-Host "YangRadar is ready: $FrontendUrl" -ForegroundColor Green
