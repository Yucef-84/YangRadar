$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$RuntimeDir = Join-Path $Root ".runtime"
$StoppedAny = $false

function Stop-YangRadarProcess {
  param(
    [string]$PidFile,
    [int]$Port,
    [string]$Endpoint,
    [string]$ExpectedContent
  )

  if (-not (Test-Path $PidFile)) {
    return
  }

  $ProcessIdText = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
  $ProcessIdValue = 0
  if (-not [int]::TryParse($ProcessIdText, [ref]$ProcessIdValue)) {
    Remove-Item -LiteralPath $PidFile -Force
    return
  }

  $NetstatPattern = "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+$ProcessIdValue\s*$"
  $OwnsExpectedPort = @(& netstat.exe -ano -p tcp) -match $NetstatPattern
  $IsExpectedApp = $false
  if ($OwnsExpectedPort) {
    try {
      $Response = Invoke-WebRequest -Uri $Endpoint -UseBasicParsing -TimeoutSec 2
      $IsExpectedApp = $Response.Content -like "*$ExpectedContent*"
    } catch {
      $IsExpectedApp = $false
    }
  }

  if ($OwnsExpectedPort -and $IsExpectedApp) {
    try {
      Stop-Process -Id $ProcessIdValue -Force -ErrorAction Stop
      $script:StoppedAny = $true
    } catch {
      Write-Host "Could not stop PID $ProcessIdValue. Try running Stop YangRadar.cmd as administrator." -ForegroundColor Red
    }
  }

  Remove-Item -LiteralPath $PidFile -Force
}

Stop-YangRadarProcess `
  -PidFile (Join-Path $RuntimeDir "frontend.pid") `
  -Port 4173 `
  -Endpoint "http://127.0.0.1:4173" `
  -ExpectedContent "YangRadar"
Stop-YangRadarProcess `
  -PidFile (Join-Path $RuntimeDir "backend.pid") `
  -Port 8001 `
  -Endpoint "http://127.0.0.1:8001/api/health" `
  -ExpectedContent '"status":"ok"'

if ($StoppedAny) {
  Write-Host "YangRadar has been stopped." -ForegroundColor Green
} else {
  Write-Host "No YangRadar process started by this launcher was found." -ForegroundColor Yellow
}
