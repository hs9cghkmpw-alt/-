param(
    [int]$SampleLimit = 8
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
Set-Location $ProjectRoot

$EvalPython = Join-Path $ProjectRoot ".venv-organizer\Scripts\python.exe"
if (-not (Test-Path $EvalPython)) {
    throw "Organizer evaluation venv is missing. Run .\scripts\setup_organizer_eval_windows.ps1 first."
}
if ($SampleLimit -lt 1 -or $SampleLimit -gt 32) {
    throw "SampleLimit must be between 1 and 32 for smoke execution."
}

& $EvalPython (Join-Path $ProjectRoot "scripts\preflight_organizer_windows.py")
if ($LASTEXITCODE -ne 0) { throw "Organizer Windows preflight failed." }

# Network is intentionally used only for this one pinned snapshot acquisition.
& $EvalPython (Join-Path $ProjectRoot "scripts\acquire_organizer_models.py") --candidate-id qwen3.5-0.8b
if ($LASTEXITCODE -ne 0) { throw "Qwen3.5-0.8B acquisition failed." }

# Model execution itself is local-files-only/offline.
& $EvalPython (Join-Path $ProjectRoot "scripts\run_organizer_open_matrix.py") `
    --candidate-id qwen3.5-0.8b `
    --sample-limit $SampleLimit `
    --determinism-samples ([Math]::Min(2, $SampleLimit)) `
    --determinism-repeats 2
if ($LASTEXITCODE -ne 0) { throw "Qwen3.5-0.8B organizer smoke failed." }

Write-Host ""
Write-Host "[OK] Qwen3.5-0.8B organizer smoke completed."
Write-Host "Do not download the 2B model yet if this smoke produced loader/schema/runtime errors."
Write-Host "If the smoke is clean, the next comparison step is:"
Write-Host "  .\.venv-organizer\Scripts\python.exe scripts\acquire_organizer_models.py --candidate-id qwen3.5-2b"
Write-Host "  .\.venv-organizer\Scripts\python.exe scripts\run_organizer_open_matrix.py --tier core"
