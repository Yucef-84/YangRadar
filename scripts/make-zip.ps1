$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ReleaseDir = Join-Path $Root "release"
$StageDir = Join-Path $ReleaseDir "YangRadar"
$ZipPath = Join-Path $ReleaseDir "YangRadar.zip"

if (Test-Path $StageDir) {
  Remove-Item -LiteralPath $StageDir -Recurse -Force
}
if (Test-Path $ZipPath) {
  Remove-Item -LiteralPath $ZipPath -Force
}
New-Item -ItemType Directory -Path $StageDir | Out-Null

$ExcludeDirs = @(".git", ".venv", "node_modules", "dist", "release", "__pycache__")
$ExcludeFiles = @(".env", "backend-server.log", "backend-server.err.log", "backend-server.pid", "frontend-server.pid", "yangradar-review.png")

Get-ChildItem -Path $Root -Force | ForEach-Object {
  if ($ExcludeDirs -contains $_.Name) { return }
  if ($ExcludeFiles -contains $_.Name) { return }
  if ($_.Name -like "*.pyc" -or $_.Name -like "*.log" -or $_.Name -like "*.pid") { return }

  $Destination = Join-Path $StageDir $_.Name
  Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
}

Get-ChildItem -Path $StageDir -Recurse -Force | Where-Object {
  $_.FullName -match "\\node_modules\\" -or
  $_.FullName -match "\\dist\\" -or
  $_.FullName -match "\\__pycache__\\" -or
  $_.Name -eq ".env" -or
  $_.Name -like "*.pyc" -or
  $_.Name -like "*.log" -or
  $_.Name -like "*.pid" -or
  $_.Name -like "*.sqlite3"
} | Remove-Item -Recurse -Force

Get-ChildItem -Path $StageDir -Recurse -Force -Directory | Where-Object {
  $ExcludeDirs -contains $_.Name
} | Sort-Object FullName -Descending | Remove-Item -Recurse -Force

Compress-Archive -Path (Join-Path $StageDir "*") -DestinationPath $ZipPath -Force

Write-Host "Created $ZipPath"
Write-Host "Send only this ZIP file. Do not send .env separately."
