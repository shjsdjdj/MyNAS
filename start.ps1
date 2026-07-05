$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = 'python'
# Local development uses plain HTTP. Production deployments behind HTTPS should
# explicitly set MYNAS_COOKIE_SECURE=true before starting MyNAS.
if (-not $env:MYNAS_COOKIE_SECURE) { $env:MYNAS_COOKIE_SECURE = 'false' }
Write-Host 'Starting MyNAS backend: http://127.0.0.1:8000' -ForegroundColor Cyan
Start-Process -FilePath $Python -ArgumentList '-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory $Root -WindowStyle Hidden
Write-Host 'Starting MyNAS frontend: http://127.0.0.1:5173' -ForegroundColor Cyan
Start-Process -FilePath 'npm.cmd' -ArgumentList 'run','dev' -WorkingDirectory $Root -WindowStyle Hidden
Start-Sleep -Seconds 3
Start-Process 'http://127.0.0.1:5173'
