[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$SkipAcquire,
    [int]$WarmRepeats = 3,
    [string]$OutDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "== Brain Twin PA1 full open-development model matrix =="
Write-Host "project: $ProjectRoot"

$trackedChanges = @(git status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw "git status failed" }
if ($trackedChanges.Count -gt 0) {
    throw "Tracked working-tree changes detected. Commit/stash them before an evidence run."
}
$GitCommit = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $GitCommit.Length -ne 40) { throw "could not resolve git HEAD" }
Write-Host "git commit: $GitCommit"

if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmssZ")
    $OutDir = ".evaluation-results\pa1-full-open-matrix\$($GitCommit.Substring(0, 8))-$stamp"
}
if ([System.IO.Path]::IsPathRooted($OutDir)) {
    $OutputRoot = [System.IO.Path]::GetFullPath($OutDir)
} else {
    $OutputRoot = [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $OutDir))
}
if (Test-Path $OutputRoot) {
    $existing = @(Get-ChildItem -LiteralPath $OutputRoot -Force)
    if ($existing.Count -gt 0) {
        throw "Output directory is not empty: $OutputRoot. Use a new -OutDir so evidence from separate runs cannot mix."
    }
} else {
    New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
}

$QwenOut = Join-Path $OutputRoot "qwen"
$ChallengerOut = Join-Path $OutputRoot "challengers"
$QwenScript = Join-Path $PSScriptRoot "run_pa1_qwen_matrix.ps1"
$ChallengerScript = Join-Path $PSScriptRoot "run_pa1_challenger_matrix.ps1"

$qwenParams = @{
    WarmRepeats = $WarmRepeats
    OutDir = $QwenOut
}
if ($SkipInstall) { $qwenParams["SkipInstall"] = $true }
if ($SkipAcquire) { $qwenParams["SkipAcquire"] = $true }

Write-Host "`n=== Stage A: Qwen instruction/dimension/reranker matrix ==="
& $QwenScript @qwenParams

# Qwen stage either created/validated the evaluation venv already. Re-use that exact runtime
# for challengers instead of performing a second package installation.
$challengerParams = @{
    SkipInstall = $true
    WarmRepeats = $WarmRepeats
    OutDir = $ChallengerOut
}
if ($SkipAcquire) { $challengerParams["SkipAcquire"] = $true }

Write-Host "`n=== Stage B: fixed-profile challenger matrix ==="
& $ChallengerScript @challengerParams

$Python = Join-Path (Join-Path $ProjectRoot ".venv-pa1-eval") "Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "evaluation Python disappeared after child matrices" }

Write-Host "`n=== Stage C: combined open-development comparison ==="
& $Python "scripts\summarize_pa1_open_matrix.py" `
    --root $OutputRoot `
    --out-json (Join-Path $OutputRoot "combined_matrix_summary.json") `
    --out-md (Join-Path $OutputRoot "combined_matrix_summary.md")
if ($LASTEXITCODE -ne 0) { throw "combined matrix summary failed" }
$Summary = Get-Content (Join-Path $OutputRoot "combined_matrix_summary.json") -Raw | ConvertFrom-Json
if ($null -eq $Summary.dense_winner -or $null -eq $Summary.overall_open_winner) {
    throw "No selection-eligible combined winner. Drifted reports remain diagnostic only."
}

$handoff = [ordered]@{
    schema = 1
    scope = "open-development-only"
    git_commit = $GitCommit
    qwen_evidence_dir = "qwen"
    challenger_evidence_dir = "challengers"
    combined_summary = "combined_matrix_summary.md"
    dense_winner = $Summary.dense_winner.candidate_id
    overall_open_winner = $Summary.overall_open_winner.candidate_id
    formal_blind_acceptance = $false
    production_activation = $false
}
$handoff | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $OutputRoot "run_handoff.json")

Write-Host "`n== PA1 full open matrix complete =="
Write-Host "Dense winner: $($Summary.dense_winner.candidate_id)"
Write-Host "Overall open winner: $($Summary.overall_open_winner.candidate_id)"
Write-Host "Combined summary: $(Join-Path $OutputRoot 'combined_matrix_summary.md')"
Write-Host "NOTE: open-development evidence only. Formal blind acceptance and production activation remain false."
