$ErrorActionPreference = "Stop"

function Invoke-QualityStep {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Quality step failed with exit code $LASTEXITCODE" }
}

$previousLogDir = $env:TINIX_LOG_DIR
$testLogDir = Join-Path ([System.IO.Path]::GetTempPath()) ("tinix-facebook-hunter-tests-" + [guid]::NewGuid().ToString("N"))
$env:TINIX_LOG_DIR = $testLogDir

try {
    Invoke-QualityStep { python -m pip check }
    Invoke-QualityStep { python -m ruff check web core/database_maintenance.py core/data_cleanup.py core/storage_migration.py manage_database.py utils/process_cleanup.py utils/secure_store.py tests }
    Invoke-QualityStep { python -m mypy web/models.py web/security.py web/ws_manager.py core/database_maintenance.py core/data_cleanup.py core/storage_migration.py }
    Invoke-QualityStep { python -m coverage erase }
    Invoke-QualityStep { python -m coverage run -m pytest -q }
    Invoke-QualityStep { python -m coverage report }
    Invoke-QualityStep { node --check web/static/app.js }
}
finally {
    if ($null -eq $previousLogDir) { Remove-Item Env:TINIX_LOG_DIR -ErrorAction SilentlyContinue }
    else { $env:TINIX_LOG_DIR = $previousLogDir }
    Remove-Item -LiteralPath $testLogDir -Recurse -Force -ErrorAction SilentlyContinue
}
