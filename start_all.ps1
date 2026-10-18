# start_all.ps1 - Reliable startup orchestrator for Yatra Canonical Services
[CmdletBinding()]
param (
    [int]$TimeoutSeconds = 30,
    [switch]$Wait
)

$ErrorActionPreference = "Stop"
$rootDir = $PSScriptRoot
$canonicalDir = Join-Path $rootDir "Yatra Saathi"
$backendDir = Join-Path $canonicalDir "backend"
$aiDir = Join-Path $canonicalDir "ai"
$frontendDir = Join-Path $canonicalDir "frontend"
$logsDir = Join-Path $rootDir ".logs"
$pidsFile = Join-Path $logsDir "pids.json"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "         Yatra Canonical Application Startup               " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Workspace Root  : $rootDir" -ForegroundColor Gray
Write-Host "Canonical Root  : $canonicalDir" -ForegroundColor Gray

# 1. Ensure logs directory exists
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

# 2. Configuration & Pre-flight Integrity Checks (Zero Secret Exposure)
Write-Host "`n[1/5] Verifying configuration and environments..." -ForegroundColor Yellow

$backendEnv = Join-Path $backendDir ".env.backend"
$aiEnv = Join-Path $aiDir ".env.agent"
$frontendEnv = Join-Path $frontendDir ".env.local"

if (-not (Test-Path $backendEnv)) {
    Write-Error "Missing required backend configuration: $backendEnv"
    exit 1
}
if (-not (Test-Path $aiEnv)) {
    Write-Error "Missing required AI agent configuration: $aiEnv"
    exit 1
}
if (-not (Test-Path $frontendEnv)) {
    Write-Error "Missing required frontend configuration: $frontendEnv"
    exit 1
}

# Python executables
$backendPython = (Join-Path $backendDir ".venv\Scripts\python.exe")
if (-not (Test-Path $backendPython)) {
    $backendPython = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $backendPython -or -not (Test-Path $backendPython)) {
    Write-Error "Backend Python interpreter not found in $backendDir\.venv\Scripts\python.exe"
    exit 1
}

$aiPython = (Join-Path $aiDir ".venv\Scripts\python.exe")
if (-not (Test-Path $aiPython)) {
    $aiPython = $backendPython
}

# Node / NPM
$npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
if (-not $npmCmd) {
    $npmCmd = (Get-Command npm -ErrorAction SilentlyContinue)
}
if (-not $npmCmd) {
    Write-Error "Node.js / npm not found in system PATH."
    exit 1
}

# Check SQLite Databases
$origDb = Join-Path $canonicalDir "data\original\APS-01.db"
$workingDb = Join-Path $backendDir "var\aps01_working.db"

if (-not (Test-Path $origDb)) {
    Write-Error "Original protected database not found at $origDb"
    exit 1
}
if (-not (Test-Path $workingDb)) {
    Write-Error "Working database not found at $workingDb"
    exit 1
}

Write-Host "  -> Backend env      : Present" -ForegroundColor Green
Write-Host "  -> AI Agent env     : Present" -ForegroundColor Green
Write-Host "  -> Frontend env     : Present" -ForegroundColor Green
Write-Host "  -> Original DB      : Verified ($origDb)" -ForegroundColor Green
Write-Host "  -> Working DB       : Verified ($workingDb)" -ForegroundColor Green
Write-Host "  -> Backend Python   : Verified ($backendPython)" -ForegroundColor Green
Write-Host "  -> AI Python        : Verified ($aiPython)" -ForegroundColor Green

# 3. Port Check & Duplicate Detection
Write-Host "`n[2/5] Checking target ports (8000, 9000, 5173)..." -ForegroundColor Yellow

function Test-HttpEndpoint([string]$url) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400)
    } catch {
        return $false
    }
}

$portDefs = @{
    8000 = @{ Name = "Backend"; HealthUrl = "http://127.0.0.1:8000/api/v1/health" }
    9000 = @{ Name = "AI Agent"; HealthUrl = "http://127.0.0.1:9000/health" }
    5173 = @{ Name = "Frontend"; HealthUrl = "http://127.0.0.1:5173/" }
}

$alreadyRunning = @{}

foreach ($port in $portDefs.Keys) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        $existingPid = $conn.OwningProcess
        $srvInfo = $portDefs[$port]
        if (Test-HttpEndpoint $srvInfo.HealthUrl) {
            Write-Host "  -> Port $port ($($srvInfo.Name)) is already listening and healthy (PID $existingPid)." -ForegroundColor Cyan
            $alreadyRunning[$srvInfo.Name] = $existingPid
        } else {
            Write-Host "  -> Port $port is occupied by PID $existingPid (unresponsive), stopping stale process..." -ForegroundColor Yellow
            Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 500
        }
    }
}

# 4. Launch Services in Clean Background Sessions
Write-Host "`n[3/5] Starting canonical services..." -ForegroundColor Yellow

$backendLog = Join-Path $logsDir "backend.log"
$aiLog = Join-Path $logsDir "ai.log"
$frontendLog = Join-Path $logsDir "frontend.log"

if (-not $alreadyRunning.ContainsKey("Backend")) {
    "" | Out-File $backendLog -Encoding utf8
    Write-Host "  -> Launching Backend on port 8000 (log: $backendLog)..." -ForegroundColor Cyan
    $bArg = "/c `"`"$backendPython`" -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --env-file .env.backend > `"$backendLog`" 2>&1`""
    Start-Process cmd.exe -ArgumentList $bArg -WorkingDirectory $backendDir -WindowStyle Hidden
}

if (-not $alreadyRunning.ContainsKey("AI Agent")) {
    "" | Out-File $aiLog -Encoding utf8
    Write-Host "  -> Launching AI Agent on port 9000 (log: $aiLog)..." -ForegroundColor Cyan
    $aArg = "/c `"`"$aiPython`" -m uvicorn service:app --host 127.0.0.1 --port 9000 --env-file .env.agent > `"$aiLog`" 2>&1`""
    Start-Process cmd.exe -ArgumentList $aArg -WorkingDirectory $aiDir -WindowStyle Hidden
}

if (-not $alreadyRunning.ContainsKey("Frontend")) {
    "" | Out-File $frontendLog -Encoding utf8
    Write-Host "  -> Launching Frontend on port 5173 (log: $frontendLog)..." -ForegroundColor Cyan
    $fArg = "/c `"`"$($npmCmd.Source)`" run dev -- --host 127.0.0.1 --port 5173 > `"$frontendLog`" 2>&1`""
    Start-Process cmd.exe -ArgumentList $fArg -WorkingDirectory $frontendDir -WindowStyle Hidden
}

# 5. Wait for Readiness via Registered Health Probes
Write-Host "`n[4/5] Probing service health endpoints (timeout: ${TimeoutSeconds}s)..." -ForegroundColor Yellow

$servicesToProbe = @(
    @{ Name = "Backend"; Port = 8000; Url = "http://127.0.0.1:8000/api/v1/health"; Log = $backendLog }
    @{ Name = "AI Agent"; Port = 9000; Url = "http://127.0.0.1:9000/health"; Log = $aiLog }
    @{ Name = "Frontend"; Port = 5173; Url = "http://127.0.0.1:5173/"; Log = $frontendLog }
)

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$allHealthy = $false

while ((Get-Date) -lt $deadline) {
    $readyCount = 0
    foreach ($svc in $servicesToProbe) {
        if (Test-HttpEndpoint $svc.Url) {
            $readyCount++
        }
    }
    if ($readyCount -eq $servicesToProbe.Count) {
        $allHealthy = $true
        break
    }
    Start-Sleep -Seconds 1
}

# Collect actual listening PIDs
$resolvedPids = @{}
foreach ($svc in $servicesToProbe) {
    $conn = Get-NetTCPConnection -LocalPort $svc.Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        $resolvedPids[$svc.Name] = $conn.OwningProcess
    }
}
$resolvedPids | ConvertTo-Json | Out-File $pidsFile -Encoding utf8

if (-not $allHealthy) {
    Write-Host "`n[ERROR] One or more services failed to report healthy within $TimeoutSeconds seconds!" -ForegroundColor Red
    foreach ($svc in $servicesToProbe) {
        $isOk = Test-HttpEndpoint $svc.Url
        if (-not $isOk) {
            Write-Host "`n--- Tail of $($svc.Name) Log ($($svc.Log)) ---" -ForegroundColor Red
            if (Test-Path $svc.Log) { Get-Content $svc.Log -Tail 20 }
        }
    }
    exit 1
}

# 6. Service Status Summary
Write-Host "`n[5/5] All Yatra canonical services are RUNNING and HEALTHY!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host ("{0,-15} {1,-8} {2,-8} {3,-38} {4}" -f "SERVICE", "PORT", "PID", "HEALTH ENDPOINT", "STATUS") -ForegroundColor White
Write-Host ("{0,-15} {1,-8} {2,-8} {3,-38} {4}" -f "-------", "----", "---", "---------------", "------") -ForegroundColor Gray
Write-Host ("{0,-15} {1,-8} {2,-8} {3,-38} {4}" -f "Backend API", "8000", $resolvedPids["Backend"], "http://127.0.0.1:8000/api/v1/health", "HEALTHY") -ForegroundColor Green
Write-Host ("{0,-15} {1,-8} {2,-8} {3,-38} {4}" -f "AI Agent", "9000", $resolvedPids["AI Agent"], "http://127.0.0.1:9000/health", "HEALTHY") -ForegroundColor Green
Write-Host ("{0,-15} {1,-8} {2,-8} {3,-38} {4}" -f "Frontend", "5173", $resolvedPids["Frontend"], "http://127.0.0.1:5173/", "HEALTHY") -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "`nApplication is ready at: http://localhost:5173" -ForegroundColor Cyan
Write-Host "To stop all services, run: .\stop_all.ps1`n" -ForegroundColor Gray

if ($Wait) {
    Write-Host "Services are running. Press Ctrl+C or run .\stop_all.ps1 to terminate." -ForegroundColor Cyan
    try {
        while ($true) {
            Start-Sleep -Seconds 2
        }
    } finally {
        Write-Host "Shutdown signal received. Stopping services..." -ForegroundColor Yellow
        & (Join-Path $rootDir "stop_all.ps1")
    }
}
