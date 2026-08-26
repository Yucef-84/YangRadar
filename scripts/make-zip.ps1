$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ReleaseDir = Join-Path $Root "release"
$StageDir = Join-Path $ReleaseDir "YangRadar"
$ZipPath = Join-Path $ReleaseDir "YangRadar.zip"
$TempZipPath = Join-Path $ReleaseDir "YangRadar.tmp.zip"

function Remove-PackagingOutput {
  if (Test-Path -LiteralPath $StageDir) {
    Remove-Item -LiteralPath $StageDir -Recurse -Force -ErrorAction SilentlyContinue
  }
  if (Test-Path -LiteralPath $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
  }
  if (Test-Path -LiteralPath $TempZipPath) {
    Remove-Item -LiteralPath $TempZipPath -Force -ErrorAction SilentlyContinue
  }
}

function Test-SensitiveRelativePath {
  param([Parameter(Mandatory = $true)][string]$RelativePath)

  $NormalizedPath = $RelativePath.Replace('\', '/')
  $LeafName = $NormalizedPath.Split('/')[-1]

  if ($LeafName -ieq '.env.example') {
    return $false
  }
  if ($LeafName -match '(?i)^\.env(?:\..*)?$') {
    return $true
  }
  if ($LeafName -match '(?i)\.(?:sqlite3|sqlite3-wal|sqlite3-shm|log|pid|pem|key|p12|pfx)$') {
    return $true
  }
  if ($NormalizedPath -match '(?i)(^|/)(?:\.runtime|\.venv|release|node_modules|dist|__pycache__|data)(?:/|$)') {
    return $true
  }

  return $false
}

Remove-PackagingOutput

try {
  New-Item -ItemType Directory -Path $StageDir -Force | Out-Null

  $TrackedPaths = @(& git -C $Root ls-files)
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to read the Git tracked-file manifest from $Root"
  }
  $TrackedPaths = @($TrackedPaths | ForEach-Object { [string]$_ } | Where-Object { $_ -ne '' })
  if ($TrackedPaths.Count -eq 0) {
    throw "Unable to create release ZIP because the Git tracked-file manifest is empty"
  }

  $SensitiveTrackedPaths = @($TrackedPaths | Where-Object {
    Test-SensitiveRelativePath -RelativePath $_
  })
  if ($SensitiveTrackedPaths.Count -gt 0) {
    throw "Refusing to create release ZIP because sensitive tracked files were found: $($SensitiveTrackedPaths -join ', ')"
  }

  foreach ($RelativePath in $TrackedPaths) {
    $SourcePath = Join-Path $Root $RelativePath
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
      throw "Tracked file is missing from the working tree: $RelativePath"
    }

    $DestinationPath = Join-Path $StageDir $RelativePath
    $DestinationParent = Split-Path -Parent $DestinationPath
    if (-not (Test-Path -LiteralPath $DestinationParent -PathType Container)) {
      New-Item -ItemType Directory -Path $DestinationParent -Force | Out-Null
    }
    Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
  }

  $SensitiveStagedPaths = @(Get-ChildItem -Path $StageDir -Recurse -File -Force | ForEach-Object {
    $StagedRelativePath = $_.FullName.Substring($StageDir.Length) -replace '^[\\/]+', ''
    $StagedRelativePath = $StagedRelativePath -replace '\\', '/'
    if (Test-SensitiveRelativePath -RelativePath $StagedRelativePath) {
      $StagedRelativePath
    }
  })
  if ($SensitiveStagedPaths.Count -gt 0) {
    throw "Refusing to create release ZIP because sensitive staged files were found: $($SensitiveStagedPaths -join ', ')"
  }

  Compress-Archive -Path (Join-Path $StageDir "*") -DestinationPath $TempZipPath -Force
  Move-Item -LiteralPath $TempZipPath -Destination $ZipPath -Force
}
catch {
  Remove-PackagingOutput
  throw
}

Write-Host "Created $ZipPath"
Write-Host "Send only this ZIP file. Do not send .env separately."
