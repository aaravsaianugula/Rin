# Kill processes on Rin's ports (8080 = VLM, 8000 = status server)
# Run: .\scripts\kill_rin_ports.ps1

$ports = @(8080, 8000)
foreach ($port in $ports) {
    $line = netstat -ano | findstr ":$port " | findstr LISTENING
    if ($line) {
        $parts = $line.Trim() -split '\s+'
        $pid = $parts[-1]
        Write-Host "Killing PID $pid on port $port..."
        taskkill /F /PID $pid 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Host "  Done." } else { Write-Host "  Failed or already gone." }
    } else {
        Write-Host "Port $port : no process listening."
    }
}
Write-Host "Done."
exit 0
