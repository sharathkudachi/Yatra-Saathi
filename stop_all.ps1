# stop_all.ps1 - Gracefully stop Yatra services using tracked PIDs and port verification
$rootDir = $PSScriptRoot
$logsDir = Join-Path $rootDir ".logs"
$pidsFile = Join-Path $logsDir "pids.json"

Write-Host "Stopping Yatra canonical services..." -ForegroundColor Cyan

# 1. Stop tracked PIDs from pids.json
if (Test-Path $pidsFile) {
    try {
        $pidsJson = Get-Content $pidsFile -Raw | ConvertFrom-Json
        foreach ($prop in $pidsJson.PSObject.Properties) {
            $svcName = $prop.Name
            $pidToStop = $prop.Value
            if ($pidToStop) {
                $proc = Get-Process -Id $pidToStop -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Host "  -> Stopping $svcName (PID $pidToStop)..." -ForegroundColor Yellow
                    Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
                }
            }
        }
        Remove-Item $pidsFile -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Warning "Failed to parse $($pidsFile): $_"
    }
}

# 2. Verify ports 8000, 9000, 5173 and ensure no orphaned python/node instances remain
$targetPorts = @(8000, 9000, 5173)
foreach ($port in $targetPorts) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($p in $pids) {
            $proc = Get-Process -Id $p -ErrorAction SilentlyContinue
            if ($proc -and ($proc.ProcessName -match "python|node|cmd|powershell")) {
                Write-Host "  -> Stopping orphaned process $($proc.ProcessName) (PID $p) on port $port..." -ForegroundColor Yellow
                Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

Start-Sleep -Seconds 1
Write-Host "All Yatra services have been stopped." -ForegroundColor Green
