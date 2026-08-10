# Brain Twin First-time Setup (Windows PowerShell)
#
# Usage (no need to run PowerShell as Administrator):
#   cd brain-twin
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\scripts\setup.ps1
#
# NOTE: This file is intentionally written using ASCII characters only.
# Windows PowerShell 5.1 can misinterpret non-ASCII (e.g. Japanese) text in a
# .ps1 file that is saved as UTF-8 without a BOM: it may read the file using
# the system's active code page instead of UTF-8, which corrupts multi-byte
# characters and can break the parser (stray quote/paren-like bytes appear).
# To avoid this class of bug entirely, all script files under scripts/ use
# ASCII-only text. See docs/COMPLETE_GUIDE_JA.md for Japanese explanations.

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

Write-Host "== Brain Twin Setup =="
Write-Host ""

# ==================================================================
# Environment check (Docker / Ollama / Node.js / Python / Tailscale)
# ==================================================================
Write-Host "== Environment check =="

$envDocker = $false
$envOllama = $false
$envNode = $false
$envPython = $false
$envTailscale = $false

if (Get-Command docker -ErrorAction SilentlyContinue) {
    $envDocker = $true
    Write-Host "  [OK] Docker"
} else {
    Write-Host "  [--] Docker"
}

if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $envOllama = $true
    Write-Host "  [OK] Ollama"
} else {
    Write-Host "  [--] Ollama"
}

if (Get-Command node -ErrorAction SilentlyContinue) {
    $envNode = $true
    Write-Host "  [OK] Node.js  (not required to run Brain Twin itself; used only by scripts/verify_all.ps1)"
} else {
    Write-Host "  [--] Node.js  (not required to run Brain Twin itself; used only by scripts/verify_all.ps1)"
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    $envPython = $true
    Write-Host "  [OK] Python  (not required to run Brain Twin itself; used only by scripts/verify_all.ps1)"
} else {
    Write-Host "  [--] Python  (not required to run Brain Twin itself; used only by scripts/verify_all.ps1)"
}

if (Get-Command tailscale -ErrorAction SilentlyContinue) {
    $envTailscale = $true
    Write-Host "  [OK] Tailscale  (needed to access Brain Twin from iPhone; not needed for PC-only testing)"
} else {
    Write-Host "  [--] Tailscale  (needed to access Brain Twin from iPhone; not needed for PC-only testing)"
}

Write-Host ""

# --- Docker: cannot auto-install (GUI installer, WSL2 setup, reboot may be required) ---
if (-not $envDocker) {
    Write-Host "[REQUIRED] Docker was not found. Cannot auto-install it." -ForegroundColor Red
    Write-Host "           Reason: Docker Desktop needs a GUI installer, WSL2 setup, and possibly a reboot."
    Write-Host "           Please install it manually from:"
    Write-Host "             https://www.docker.com/products/docker-desktop/"
    Write-Host ""
    Write-Host "After installing Docker, run this script again."
    exit 1
}

# --- Ollama: attempt auto-install via winget if available, with confirmation ---
if (-not $envOllama) {
    Write-Host "[RECOMMENDED] Ollama was not found. It is needed for AI organizing features"
    Write-Host "              (Brain Twin itself still starts, and input/save/search work without it)."
    $autoInstalled = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $ans = Read-Host "              Run 'winget install Ollama.Ollama' now? [y/N]"
        if ($ans -eq "y" -or $ans -eq "Y") {
            winget install --id Ollama.Ollama -e
            if ($LASTEXITCODE -eq 0) { $autoInstalled = $true }
        }
    }
    if (-not $autoInstalled) {
        Write-Host "              Auto-install was not performed (winget missing, or you chose not to)."
        Write-Host "              To install manually: https://ollama.com/download/windows"
    }
    Write-Host ""
}

# --- Tailscale: sign-in is required afterward, so only show the manual link ---
if (-not $envTailscale) {
    Write-Host "[OPTIONAL] Tailscale was not found. It is needed to access Brain Twin from iPhone"
    Write-Host "           (not needed while testing on this PC only)."
    Write-Host "           Cannot auto-install (reason: sign-in is required after installation)."
    Write-Host "           To install manually: https://tailscale.com/download/windows"
    Write-Host ""
}

if ((-not $envNode) -or (-not $envPython)) {
    Write-Host "[INFO] Node.js/Python are NOT required to run Brain Twin itself"
    Write-Host "       (everything runs inside Docker containers). Install them only if you"
    Write-Host "       also want to run the extra test suite (scripts/verify_all.ps1) on this PC:"
    if (-not $envNode) { Write-Host "         Node.js: https://nodejs.org" }
    if (-not $envPython) { Write-Host "         Python : https://www.python.org/downloads/" }
    Write-Host ""
}

# ==================================================================
# Main setup
# ==================================================================

# --- Prepare .env ---
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[OK] Created .env (copied from .env.example). Edit it later if you need to change settings."
} else {
    Write-Host "[SKIP] .env already exists."
}

New-Item -ItemType Directory -Force -Path "data\database" | Out-Null
New-Item -ItemType Directory -Force -Path "data\backups" | Out-Null
New-Item -ItemType Directory -Force -Path "data\exports" | Out-Null
Write-Host "[OK] Prepared the data\ directory."

# --- Check Ollama models ---
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $models = ollama list 2>$null
    $missingModels = @()
    if (-not ($models -match "qwen2.5")) { $missingModels += "qwen2.5:7b-instruct" }
    if (-not ($models -match "bge-m3")) { $missingModels += "bge-m3" }
    if ($missingModels.Count -gt 0) {
        Write-Host "[INFO] The following model(s) were not found. Run these later:"
        foreach ($m in $missingModels) { Write-Host "    ollama pull $m" }
    }
} else {
    Write-Host "[INFO] To run Ollama inside Docker instead, start it like this:"
    Write-Host "          docker compose --profile dockerized-ollama up -d ollama"
    Write-Host "          docker compose exec ollama ollama pull qwen2.5:7b-instruct"
    Write-Host "          docker compose exec ollama ollama pull bge-m3"
    Write-Host "          (also set OLLAMA_BASE_URL=http://ollama:11434 in .env)"
}

# --- Build & start ---
Write-Host "== Building Docker images (first time may take a few minutes) =="
docker compose build

Write-Host "== Starting containers =="
docker compose up -d

Write-Host "== Applying the latest database schema =="
docker compose exec -T server alembic upgrade head

# --- Ollama pre-flight check ---
Write-Host "== Ollama pre-flight check (informational only; setup continues even if this fails) =="
docker compose exec -T server python scripts/ollama_preflight.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "[INFO] Some Ollama checks reported issues, but setup will continue." -ForegroundColor Yellow
}

# --- Health check ---
$envContent = Get-Content ".env" | Where-Object { $_ -match "^WEB_PORT=" }
$webPort = if ($envContent) { ($envContent -split "=")[1] } else { "8080" }
if ([string]::IsNullOrWhiteSpace($webPort)) { $webPort = "8080" }

Write-Host "== Health check =="
$healthy = $false
for ($i = 0; $i -lt 15; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$webPort/api/health" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) {
            Write-Host "[OK] Server is up (via http://127.0.0.1:$webPort ; /api is forwarded to server by Nginx)"
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}
if (-not $healthy) {
    Write-Host "[WARNING] Timed out waiting for the server. Check 'docker compose logs server' and 'docker compose logs web'." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "== Next step: pair with your iPhone =="
Write-Host "Run the following to issue a pairing code to type into the iPhone app:"
Write-Host "(This command only works when run on the PC itself; it is not exposed on the public web endpoint.)"
Write-Host ""
Write-Host "    docker compose exec server curl -s -X POST http://localhost:8000/api/pairing/start"
Write-Host ""
Write-Host "Enter the 'code' shown above into Brain Twin on your iPhone (after adding it to the Home Screen)."
Write-Host "The iPhone should open the same address as http://127.0.0.1:$webPort (the URL published via tailscale serve)."
Write-Host "See docs/SETUP_IPHONE.md and docs/TAILSCALE_SETUP.md for details."
Write-Host ""
Write-Host "Setup is complete. Thank you for your patience."
