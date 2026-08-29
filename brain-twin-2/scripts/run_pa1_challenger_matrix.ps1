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

$ReadyCandidateIds = @(
    "bge-m3",
    "multilingual-e5-base",
    "multilingual-e5-large-instruct",
    "multilingual-minilm-control"
)

Write-Host "== Brain Twin PA1 fixed-profile challenger matrix =="
Write-Host "project: $ProjectRoot"

$trackedChanges = @(git status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw "git status failed" }
if ($trackedChanges.Count -gt 0) {
    throw "Tracked working-tree changes detected. Commit/stash them before an evidence run."
}

$GitCommit = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $GitCommit.Length -ne 40) { throw "could not resolve git HEAD" }
Write-Host "git commit: $GitCommit"

$Venv = Join-Path $ProjectRoot ".venv-pa1-eval"
$Python = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Python)) {
    if ($SkipInstall) { throw "evaluation venv is missing and -SkipInstall was requested" }
    Write-Host "Creating Python 3.12 evaluation venv..."
    & py -3.12 -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "failed to create Python 3.12 venv" }
}

if (-not $SkipInstall) {
    Write-Host "Installing reviewed evaluation runtime..."
    & $Python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }
    & $Python -m pip install "torch==2.13.0" "sentence-transformers==5.4.1" "huggingface-hub==1.28.0"
    if ($LASTEXITCODE -ne 0) { throw "evaluation dependency install failed" }
}

if (-not $env:LOCALAPPDATA) { throw "LOCALAPPDATA is required on the Windows PA1 machine" }
$ModelRoot = Join-Path $env:LOCALAPPDATA "BrainTwin\models"

if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmssZ")
    $OutDir = ".evaluation-results\pa1-challenger-matrix\$($GitCommit.Substring(0, 8))-$stamp"
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
Write-Host "evidence root: $OutputRoot"

$EvidenceDir = Join-Path $OutputRoot "environment"
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
& $Python -m pip freeze | Set-Content -Encoding UTF8 (Join-Path $EvidenceDir "pip-freeze.txt")

$PlanPath = Join-Path $EvidenceDir "challenger_plan.json"
& $Python "scripts\plan_pa1_challengers.py" --out $PlanPath
if ($LASTEXITCODE -ne 0) { throw "challenger planning failed" }
$Plan = Get-Content $PlanPath -Raw | ConvertFrom-Json
$RunnableRuns = @($Plan.runs | Where-Object { $_.runnable -eq $true })
$BlockedRuns = @($Plan.runs | Where-Object { $_.runnable -ne $true })
if ($RunnableRuns.Count -eq 0) { throw "challenger plan contains no runnable candidates" }

# The catalog may contain pinned candidates that intentionally remain blocked behind a custom-code
# smoke gate. Never silently promote them into this evidence run.
$UnexpectedRunnable = @(
    $RunnableRuns | Where-Object { $ReadyCandidateIds -notcontains ([string]$_.candidate_id) }
)
if ($UnexpectedRunnable.Count -gt 0) {
    $names = ($UnexpectedRunnable | ForEach-Object { [string]$_.candidate_id }) -join ", "
    throw "challenger plan enabled an unreviewed runnable candidate: $names"
}

if (-not $SkipAcquire) {
    Write-Host "Acquiring immutable runnable challenger snapshots..."
    $AcquireArgs = @("scripts\acquire_pa1_candidate_models.py")
    foreach ($candidateId in $ReadyCandidateIds) {
        $AcquireArgs += "--candidate-id"
        $AcquireArgs += $candidateId
    }
    & $Python @AcquireArgs
    if ($LASTEXITCODE -ne 0) { throw "challenger model acquisition failed" }
}

foreach ($run in $RunnableRuns) {
    if ($run.trust_remote_code -eq $true) {
        throw "remote-code candidate escaped the smoke gate: $($run.candidate_id)"
    }
    $ModelPath = Join-Path $ModelRoot ([string]$run.model_directory_name)
    $PinManifest = Join-Path $ModelPath "brain_twin_model_pin.json"
    if (-not (Test-Path $PinManifest)) {
        throw "pinned model not found for $($run.candidate_id) at $ModelPath"
    }

    $ExperimentId = "$($run.candidate_id)-$($run.dimension)"
    $CandidateOut = Join-Path $OutputRoot $ExperimentId
    Write-Host "`n-- challenger $ExperimentId --"
    & $Python "scripts\run_local_candidate_pipeline.py" `
        --candidate-id $ExperimentId `
        --model-path $ModelPath `
        --model-name ([string]$run.model_name) `
        --model-revision ([string]$run.model_revision) `
        --instruction-id "$($run.candidate_id)-fixed-v1" `
        --query-template-file ([string]$run.query_template_file) `
        --document-template-file ([string]$run.document_template_file) `
        --dimension ([int]$run.dimension) `
        --batch-size 4 `
        --split dev `
        --warm-repeats $WarmRepeats `
        --git-commit $GitCommit `
        --out-dir $CandidateOut
    if ($LASTEXITCODE -ne 0) { throw "challenger failed: $ExperimentId" }
}

& $Python "scripts\summarize_pa1_open_matrix.py" `
    --root $OutputRoot `
    --out-json (Join-Path $OutputRoot "matrix_summary.json") `
    --out-md (Join-Path $OutputRoot "matrix_summary.md")
if ($LASTEXITCODE -ne 0) { throw "challenger summary failed" }
$Summary = Get-Content (Join-Path $OutputRoot "matrix_summary.json") -Raw | ConvertFrom-Json

$os = $null
$cpu = $null
$computer = $null
try { $os = Get-CimInstance Win32_OperatingSystem } catch {}
try { $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 } catch {}
try { $computer = Get-CimInstance Win32_ComputerSystem } catch {}
$environment = [ordered]@{
    schema = 1
    created_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    git_commit = $GitCommit
    python = (& $Python --version 2>&1 | Out-String).Trim()
    os_caption = if ($os) { $os.Caption } else { $null }
    os_version = if ($os) { $os.Version } else { $null }
    os_architecture = if ($os) { $os.OSArchitecture } else { $null }
    cpu_name = if ($cpu) { $cpu.Name } else { $null }
    logical_processors = if ($computer) { [int]$computer.NumberOfLogicalProcessors } else { $null }
    total_physical_memory_bytes = if ($computer) { [int64]$computer.TotalPhysicalMemory } else { $null }
    model_store_policy = "repo-external"
    benchmark_scope = "open-development-only"
    runnable_candidate_ids = @($RunnableRuns | ForEach-Object { [string]$_.candidate_id } | Select-Object -Unique)
    smoke_blocked_candidate_ids = @($BlockedRuns | ForEach-Object { [string]$_.candidate_id } | Select-Object -Unique)
}
$environment | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $EvidenceDir "environment.json")

Write-Host "`n== PA1 challenger matrix complete =="
Write-Host "Dense challenger winner: $($Summary.dense_winner.candidate_id)"
Write-Host "Summary: $(Join-Path $OutputRoot 'matrix_summary.md')"
Write-Host "Blocked candidates remain excluded until their isolated custom-code smoke is reviewed."
Write-Host "NOTE: this is open-development evidence, not formal blind acceptance or production activation."
