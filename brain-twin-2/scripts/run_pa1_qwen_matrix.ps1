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

$EmbeddingRevision = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
$RerankerRevision = "e61197ed45024b0ed8a2d74b80b4d909f1255473"
$EmbeddingName = "Qwen/Qwen3-Embedding-0.6B"
$RerankerName = "Qwen/Qwen3-Reranker-0.6B"

Write-Host "== Brain Twin PA1 Qwen open-benchmark matrix =="
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
$EmbeddingPath = Join-Path $ModelRoot "Qwen3-Embedding-0.6B_97b0c614"
$RerankerPath = Join-Path $ModelRoot "Qwen3-Reranker-0.6B_e61197ed"

if (-not $SkipAcquire) {
    Write-Host "Acquiring immutable Qwen snapshots..."
    & $Python "scripts\acquire_pa1_qwen_models.py" --role both
    if ($LASTEXITCODE -ne 0) { throw "model acquisition failed" }
}
if (-not (Test-Path (Join-Path $EmbeddingPath "brain_twin_model_pin.json"))) {
    throw "pinned embedding model not found at $EmbeddingPath"
}
if (-not (Test-Path (Join-Path $RerankerPath "brain_twin_model_pin.json"))) {
    throw "pinned reranker model not found at $RerankerPath"
}

if ([string]::IsNullOrWhiteSpace($OutDir)) {
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmssZ")
    $OutDir = ".evaluation-results\pa1-qwen-matrix\$($GitCommit.Substring(0, 8))-$stamp"
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
    embedding_model = $EmbeddingName
    embedding_revision = $EmbeddingRevision
    reranker_model = $RerankerName
    reranker_revision = $RerankerRevision
    model_store_policy = "repo-external"
    benchmark_scope = "open-development-only"
}
$environment | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $EvidenceDir "environment.json")

function Invoke-DenseCandidate {
    param(
        [Parameter(Mandatory=$true)][string]$Tag,
        [Parameter(Mandatory=$true)][string]$InstructionId,
        [Parameter(Mandatory=$true)][string]$TemplateFile,
        [Parameter(Mandatory=$true)][int]$Dimension
    )
    $candidateId = "qwen3-$Tag-$Dimension"
    $candidateOut = Join-Path $OutputRoot $candidateId
    Write-Host "`n-- dense $candidateId --"
    & $Python "scripts\run_local_candidate_pipeline.py" `
        --candidate-id $candidateId `
        --model-path $EmbeddingPath `
        --model-name $EmbeddingName `
        --model-revision $EmbeddingRevision `
        --instruction-id $InstructionId `
        --query-template-file $TemplateFile `
        --dimension $Dimension `
        --batch-size 8 `
        --split dev `
        --warm-repeats $WarmRepeats `
        --git-commit $GitCommit `
        --out-dir $candidateOut
    if ($LASTEXITCODE -ne 0) { throw "dense candidate failed: $candidateId" }
}

function Write-MatrixSummary {
    & $Python "scripts\summarize_pa1_qwen_matrix.py" `
        --root $OutputRoot `
        --out-json (Join-Path $OutputRoot "matrix_summary.json") `
        --out-md (Join-Path $OutputRoot "matrix_summary.md")
    if ($LASTEXITCODE -ne 0) { throw "matrix summary failed" }
    return (Get-Content (Join-Path $OutputRoot "matrix_summary.json") -Raw | ConvertFrom-Json)
}

$Profiles = @{
    "qwen3-brain-twin-en-v1" = @{ Tag = "en"; File = "evaluation_profiles\qwen3_embedding_en.txt" }
    "qwen3-brain-twin-ja-v1" = @{ Tag = "ja"; File = "evaluation_profiles\qwen3_embedding_ja.txt" }
    "qwen3-no-instruction-v1" = @{ Tag = "none"; File = "evaluation_profiles\qwen3_embedding_none.txt" }
}

# Stage 1: hold dimension fixed and compare query instructions only.
foreach ($instructionId in @("qwen3-brain-twin-en-v1", "qwen3-brain-twin-ja-v1", "qwen3-no-instruction-v1")) {
    $profile = $Profiles[$instructionId]
    Invoke-DenseCandidate -Tag $profile.Tag -InstructionId $instructionId -TemplateFile $profile.File -Dimension 1024
}
$summary = Write-MatrixSummary
$instructionWinnerId = [string]$summary.dense_winner.instruction_id
if (-not $Profiles.ContainsKey($instructionWinnerId)) {
    throw "unexpected instruction winner: $instructionWinnerId"
}
$winnerProfile = $Profiles[$instructionWinnerId]
Write-Host "`nInstruction winner (open dev): $instructionWinnerId"

# Stage 2: only the winning instruction advances to the dimensionality sweep.
foreach ($dimension in @(768, 512, 256)) {
    Invoke-DenseCandidate -Tag $winnerProfile.Tag -InstructionId $instructionWinnerId -TemplateFile $winnerProfile.File -Dimension $dimension
}
$summary = Write-MatrixSummary
$bestDense = $summary.dense_winner
$bestDimension = [int]$bestDense.dimension
Write-Host "Dense winner after dimension sweep (open dev): $($bestDense.candidate_id)"

# Stage 3: compare reranker OFF vs ON using the exact winning dense profile and a frozen top-50 pool.
$rerankOut = Join-Path $OutputRoot "best-dense-plus-reranker"
Write-Host "`n-- reranker OFF/ON on $($bestDense.candidate_id) --"
& $Python "scripts\run_local_candidate_pipeline.py" `
    --candidate-id ([string]$bestDense.candidate_id) `
    --model-path $EmbeddingPath `
    --model-name $EmbeddingName `
    --model-revision $EmbeddingRevision `
    --instruction-id $instructionWinnerId `
    --query-template-file $winnerProfile.File `
    --dimension $bestDimension `
    --batch-size 8 `
    --split dev `
    --warm-repeats 0 `
    --git-commit $GitCommit `
    --out-dir $rerankOut `
    --reranker-candidate-id "qwen3-reranker-brain-twin-v1" `
    --reranker-model-path $RerankerPath `
    --reranker-model-name $RerankerName `
    --reranker-model-revision $RerankerRevision `
    --reranker-instruction-id "qwen3-reranker-brain-twin-v1" `
    --reranker-instruction-file "evaluation_profiles\qwen3_reranker_brain_twin.txt" `
    --reranker-batch-size 4 `
    --reranker-candidate-k 50 `
    --reranker-warm-repeats 0
if ($LASTEXITCODE -ne 0) { throw "reranker comparison failed" }

# The reranker pipeline emits a duplicate copy of its dense baseline. Keep the original matrix
# baseline and only retain reranker evidence from this directory so summary rows stay unambiguous.
foreach ($name in @("dense_report.json", "dense_report.md", "dense_manifest.json", "dense_preparation.json")) {
    $path = Join-Path $rerankOut $name
    if (Test-Path $path) { Remove-Item $path -Force }
}
$summary = Write-MatrixSummary

Write-Host "`n== PA1 open matrix complete =="
Write-Host "Dense winner: $($summary.dense_winner.candidate_id)"
Write-Host "Overall open winner: $($summary.overall_open_winner.candidate_id)"
Write-Host "Summary: $(Join-Path $OutputRoot 'matrix_summary.md')"
Write-Host "NOTE: this is open-development evidence, not formal blind acceptance or production activation."
