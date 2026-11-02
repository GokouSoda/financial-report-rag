$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$indexPath = Join-Path $projectRoot "data\index\index_manifest.json"

if (-not (Test-Path -LiteralPath $indexPath)) {
    throw "Index not found. Run scripts/download_reports.py, scripts/extract_all.py, scripts/chunk_documents.py, and scripts/build_index.py first."
}

$env:HF_HUB_OFFLINE = "1"
$env:PYTHONIOENCODING = "utf-8"
$api = Start-Process -FilePath python `
    -ArgumentList "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

try {
    Write-Host "API: http://127.0.0.1:8000"
    Write-Host "Web: http://127.0.0.1:5173"
    Push-Location (Join-Path $projectRoot "web")
    npm run dev
}
finally {
    Pop-Location
    if ($api -and -not $api.HasExited) {
        Stop-Process -Id $api.Id
    }
}
