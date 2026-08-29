param(
    [switch]$SkipPull
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".." )).Path
Set-Location $ProjectRoot

if ($env:OS -ne "Windows_NT") {
    throw "Organizer evaluation bootstrap is Windows-only."
}

$branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne "brain-twin-dev") {
    throw "Expected git branch brain-twin-dev; got '$branch'."
}

$dirty = @(git status --porcelain)
if ($LASTEXITCODE -ne 0) { throw "git status failed." }
if ($dirty.Count -ne 0) {
    throw "Refusing organizer bootstrap from a dirty worktree. Commit/stash changes first."
}

if (-not $SkipPull) {
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "git pull --ff-only failed." }
}

$PythonLauncher = $null
try {
    $pyVersion = (& py -3.12 -c "import platform; print(platform.python_version())" 2>$null).Trim()
    if ($LASTEXITCODE -eq 0 -and $pyVersion.StartsWith("3.12.")) {
        $PythonLauncher = @("py", "-3.12")
    }
} catch { }

if ($null -eq $PythonLauncher) {
    $pythonVersion = (& python -c "import platform; print(platform.python_version())").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $pythonVersion.StartsWith("3.12.")) {
        throw "Python 3.12 x64 is required for the frozen organizer Windows environment."
    }
    $PythonLauncher = @("python")
}

$Venv = Join-Path $ProjectRoot ".venv-organizer"
if (-not (Test-Path $Venv)) {
    if ($PythonLauncher.Count -eq 2) {
        & $PythonLauncher[0] $PythonLauncher[1] -m venv $Venv
    } else {
        & $PythonLauncher[0] -m venv $Venv
    }
    if ($LASTEXITCODE -ne 0) { throw "Failed to create .venv-organizer." }
}

$EvalPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $EvalPython)) {
    throw "Organizer virtualenv Python was not created: $EvalPython"
}

& $EvalPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }

& $EvalPython -m pip install -r (Join-Path $ProjectRoot "evaluation_profiles\organizer_windows_requirements_v1.txt")
if ($LASTEXITCODE -ne 0) { throw "Organizer evaluation dependency installation failed." }

& $EvalPython (Join-Path $ProjectRoot "scripts\preflight_organizer_windows.py")
if ($LASTEXITCODE -ne 0) { throw "Organizer Windows preflight failed." }

Write-Host ""
Write-Host "[OK] Organizer evaluation venv ready: $Venv"
Write-Host "Next safe step:"
Write-Host "  .\scripts\smoke_organizer_qwen08_windows.ps1"
