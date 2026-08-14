# Brain Twin 2.0 (Phase 1) セットアップ (Windows PowerShell)
#
# 実行方法:
#   cd brain-twin-2
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\scripts\setup.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "== Brain Twin 2.0 セットアップ (Phase 1) =="
Write-Host ""

# --- Python確認 ---
$PythonCmd = $null
foreach ($candidate in @("python", "python3", "py")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $PythonCmd = $candidate
        break
    }
}
if (-not $PythonCmd) {
    Write-Host "[NG] Pythonが見つかりません。https://www.python.org/downloads/ からインストールしてください。" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python: $(& $PythonCmd --version)"

# --- 仮想環境作成 ---
if (-not (Test-Path ".venv")) {
    Write-Host "== 仮想環境(.venv)を作成しています =="
    & $PythonCmd -m venv .venv
} else {
    Write-Host "[SKIP] .venv は既に存在します。"
}

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"

Write-Host "== 依存パッケージをインストールしています =="
& $VenvPython -m pip install --quiet --upgrade pip
& $VenvPython -m pip install --quiet -r requirements.txt

Write-Host "== テストを実行しています(動作確認) =="
& $VenvPython -m pytest tests\ -q

Write-Host ""
Write-Host "== セットアップ完了 =="
Write-Host ""
Write-Host "使い方の例:"
Write-Host '  .\.venv\Scripts\python.exe brain.py add "今日はBrain Twinの設計について考えた"'
Write-Host '  .\.venv\Scripts\python.exe brain.py process'
Write-Host '  .\.venv\Scripts\python.exe brain.py search "Brain Twin"'
Write-Host ""
Write-Host "Vaultは既定で '$RepoRoot\vault' に作成されます。Obsidianでこのフォルダを開いてください。"
