param(
  [switch]$NoBrowser,
  [switch]$Development,
  [switch]$SkipEnvFile
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeRoot = Join-Path $Root '.tmp\launcher'
$LocalUrl = 'http://127.0.0.1:8000'
$HealthUrl = "$LocalUrl/health"
$BackendStartedByLauncher = $false
$FrontendStartedByLauncher = $false

# Some launch environments provide both Path and PATH. Windows treats them as
# the same name, while Start-Process rejects the duplicate environment block.
$ProcessEnvironment = [Environment]::GetEnvironmentVariables()
if ($ProcessEnvironment.Contains('Path') -and $ProcessEnvironment.Contains('PATH')) {
  [Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
}

function Write-Status([string]$Label, [string]$State, [ConsoleColor]$Color = 'Gray') {
  Write-Host ("[{0,-12}] {1}" -f $Label, $State) -ForegroundColor $Color
}

function Get-ListeningProcessId([int]$Port) {
  try {
    $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction Stop | Select-Object -First 1
    if ($connection) { return [int]$connection.OwningProcess }
  } catch { }
  $match = netstat -ano -p tcp | Select-String -Pattern (":$Port\s+.*LISTENING\s+(\d+)\s*$") | Select-Object -First 1
  if ($match -and $match.Matches.Count) { return [int]$match.Matches[0].Groups[1].Value }
  return $null
}

function Get-MyNASHealth {
  try {
    $request = [System.Net.HttpWebRequest]::Create($HealthUrl)
    $request.Timeout = 2000
    $request.ReadWriteTimeout = 2000
    $request.UserAgent = 'MyNAS-Launcher/3.4.0'
    try { $response = $request.GetResponse() }
    catch [System.Net.WebException] {
      if (-not $_.Exception.Response) { return $null }
      $response = $_.Exception.Response
    }
    try {
      $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
      $payload = $reader.ReadToEnd() | ConvertFrom-Json
      if ($payload.backend -ne 'running') { return $null }
      return $payload
    } finally {
      if ($reader) { $reader.Dispose() }
      if ($response) { $response.Dispose() }
    }
  } catch { return $null }
}

function Test-Tunnel {
  $urls = @()
  if ($env:MYNAS_TUNNEL_METRICS_URL) {
    try {
      $metricsUri = [Uri]$env:MYNAS_TUNNEL_METRICS_URL
      if ($metricsUri.Scheme -eq 'http' -and $metricsUri.IsLoopback -and $metricsUri.AbsolutePath -eq '/metrics') {
        $urls += $metricsUri.AbsoluteUri
      }
    } catch { }
  } else {
    20241..20245 | ForEach-Object { $urls += "http://127.0.0.1:$_/metrics" }
  }
  foreach ($url in $urls) {
    try {
      $metrics = (Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 1).Content
      $connections = [regex]::Matches($metrics, '(?m)^cloudflared_tunnel_ha_connections(?:\{[^}]*\})?\s+([0-9.]+)')
      if (($connections | ForEach-Object { [double]$_.Groups[1].Value } | Measure-Object -Sum).Sum -gt 0) { return $true }
    } catch { }
  }
  return $false
}

function Invoke-PythonPreflight(
  [string]$Label,
  [string]$Code,
  [string]$PythonPath,
  [int]$TimeoutSeconds = 30
) {
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmssfff'
  $stdoutLog = Join-Path $RuntimeRoot "preflight-$($Label.ToLowerInvariant())-$stamp.log"
  $stderrLog = Join-Path $RuntimeRoot "preflight-$($Label.ToLowerInvariant())-$stamp-error.log"
  $quotedCode = '"' + ($Code -replace '"', '\"') + '"'
  $preflightProcess = Start-Process -FilePath $PythonPath -ArgumentList '-c',$quotedCode -WorkingDirectory $Root -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -WindowStyle Hidden -PassThru
  if (-not $preflightProcess.WaitForExit($TimeoutSeconds * 1000)) {
    Stop-Process -Id $preflightProcess.Id -Force -ErrorAction SilentlyContinue
    Write-Status $Label 'preflight timed out' Red
    return $false
  }
  $preflightProcess.WaitForExit()
  $preflightOutput = if (Test-Path $stdoutLog) { Get-Content -LiteralPath $stdoutLog -Raw } else { $null }
  $preflightResult = if ($null -eq $preflightOutput) { '' } else { $preflightOutput.Trim() }
  if ($preflightResult -ne '1') {
    Write-Status $Label 'preflight failed' Red
    return $false
  }
  Write-Status $Label 'preflight ready' Green
  return $true
}

try {
  New-Item -ItemType Directory -Force -Path $RuntimeRoot | Out-Null
  $EnvFile = Join-Path $Root '.env'
  if (-not $SkipEnvFile -and (Test-Path $EnvFile)) {
    foreach ($Line in Get-Content -LiteralPath $EnvFile) {
      $NormalizedLine = $Line.TrimStart([char]0xFEFF)
      if ($NormalizedLine -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') {
        $Name = $Matches[1]
        $Value = $Matches[2].Trim()
        if ($Value.Length -ge 2 -and (($Value[0] -eq '"' -and $Value[-1] -eq '"') -or ($Value[0] -eq "'" -and $Value[-1] -eq "'"))) {
          $Value = $Value.Substring(1, $Value.Length - 2)
        }
        Set-Item -Path "Env:$Name" -Value $Value
      }
    }
  }

  if ($Development) {
    $env:MYNAS_ENV = 'development'
    $env:MYNAS_COOKIE_SECURE = 'false'
  } elseif ($env:MYNAS_PUBLIC_BASE_URL) {
    $publicUri = [Uri]$env:MYNAS_PUBLIC_BASE_URL
    if ($publicUri.Scheme -ne 'https') { throw 'Public access requires an https:// MYNAS_PUBLIC_BASE_URL.' }
    if ($env:MYNAS_COOKIE_SECURE -eq 'false') { throw 'Public access requires MYNAS_COOKIE_SECURE=true.' }
    $env:MYNAS_COOKIE_SECURE = 'true'
    if (-not $env:MYNAS_ENV) { $env:MYNAS_ENV = 'production' }
  } else {
    if (-not $env:MYNAS_ENV) { $env:MYNAS_ENV = 'development' }
    if (-not $env:MYNAS_COOKIE_SECURE) { $env:MYNAS_COOKIE_SECURE = 'false' }
  }
  if (-not $env:MYNAS_SCAN_ON_STARTUP) { $env:MYNAS_SCAN_ON_STARTUP = 'false' }

  $Candidates = @()
  if ($env:MYNAS_PYTHON) { $Candidates += $env:MYNAS_PYTHON }
  $VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
  if (Test-Path $VenvPython) { $Candidates += $VenvPython }
  $SystemPython = Get-Command python.exe -ErrorAction SilentlyContinue
  if ($SystemPython) { $Candidates += $SystemPython.Source }

  $Python = $null
  foreach ($Candidate in ($Candidates | Select-Object -Unique)) {
    try {
      $candidateVersion = (& $Candidate -c 'import sys; print(sys.version_info.major,sys.version_info.minor,sys.version_info.micro,sep=chr(46))' 2>$null | Select-Object -Last 1).Trim()
      if ([version]$candidateVersion -ge [version]'3.11.0') { $Python = $Candidate; $version = $candidateVersion; break }
      Write-Status 'Python' "candidate is older than 3.11: $Candidate" Yellow
    } catch {
      Write-Status 'Python' "candidate rejected: $Candidate ($($_.Exception.Message))" Yellow
    }
  }
  if (-not $Python) { throw 'Python 3.11+ was not found. Configure MYNAS_PYTHON or create .venv.' }
  $dependencyCheck = (& $Python -c 'import fastapi, uvicorn; print(1)' 2>$null | Select-Object -Last 1)
  if ($dependencyCheck -ne '1') { throw 'The selected Python is missing FastAPI or Uvicorn.' }
  Write-Status 'Python' "$version ($Python)" Green

  if (-not $Development -and -not (Test-Path (Join-Path $Root 'dist\index.html'))) {
    throw 'Production web assets are missing. Run npm run build once before using the desktop launcher.'
  }

  $health = Get-MyNASHealth
  if (-not $health) {
    $ownerProcessId = Get-ListeningProcessId 8000
    if ($ownerProcessId) {
      $processName = (Get-Process -Id $ownerProcessId -ErrorAction SilentlyContinue).ProcessName
      throw "Port 8000 is already occupied by PID $ownerProcessId ($processName). MyNAS did not stop that process."
    }
    if (-not (Invoke-PythonPreflight 'Storage' 'from backend import config; config.initialize_storage(); print(1)' $Python)) {
      throw 'Storage is unavailable. Review the local preflight log; no path or exception was exposed in the launcher.'
    }
    if (-not (Invoke-PythonPreflight 'Database' 'from backend.db.database import initialize_database; initialize_database(); print(1)' $Python)) {
      throw 'Database is unavailable. Review the local preflight log; no path or exception was exposed in the launcher.'
    }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stdoutLog = Join-Path $RuntimeRoot "backend-$stamp.log"
    $stderrLog = Join-Path $RuntimeRoot "backend-$stamp-error.log"
    Write-Status 'Backend' 'starting on 127.0.0.1:8000' Cyan
    $backendProcess = Start-Process -FilePath $Python -ArgumentList '-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8000','--no-server-header' -WorkingDirectory $Root -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -WindowStyle Minimized -PassThru
    $BackendStartedByLauncher = $true
    Set-Content -LiteralPath (Join-Path $RuntimeRoot 'backend.pid') -Value $backendProcess.Id
    $deadline = (Get-Date).AddSeconds(30)
    do {
      Start-Sleep -Milliseconds 500
      if ($backendProcess.HasExited) { throw "MyNAS backend exited during startup. Review $stderrLog" }
      $health = Get-MyNASHealth
    } while (-not $health -and (Get-Date) -lt $deadline)
    if (-not $health) { throw "MyNAS backend did not respond within 30 seconds. Review $stderrLog" }
  }

  if ($health.status -eq 'ok') {
    Write-Status 'Backend' 'running' Green
    Write-Status 'Database' $health.database Green
    Write-Status 'Storage' $health.storage Green
  } else {
    Write-Status 'Backend' "running, readiness error: $($health.reason)" Yellow
  }

  $BrowserUrl = $LocalUrl
  if ($Development) {
    $frontendReady = $false
    try { $frontendReady = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173/' -TimeoutSec 2).StatusCode -eq 200 } catch { }
    if (-not $frontendReady) {
      $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
      if (-not $npm) { throw 'npm.cmd was not found for -Development mode.' }
      $frontendProcess = Start-Process -FilePath $npm.Source -ArgumentList 'run','dev' -WorkingDirectory $Root -WindowStyle Minimized -PassThru
      $FrontendStartedByLauncher = $true
      $frontendDeadline = (Get-Date).AddSeconds(20)
      do {
        Start-Sleep -Milliseconds 500
        try { $frontendReady = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:5173/' -TimeoutSec 2).StatusCode -eq 200 } catch { }
      } while (-not $frontendReady -and (Get-Date) -lt $frontendDeadline)
    }
    if (-not $frontendReady) { throw 'Vite did not become ready on port 5173.' }
    Write-Status 'Frontend' 'development server ready' Green
    $BrowserUrl = 'http://127.0.0.1:5173'
  }

  if ($env:MYNAS_PUBLIC_BASE_URL) {
    $tunnelHealthy = Test-Tunnel
    if (-not $tunnelHealthy) {
      $service = Get-Service -Name cloudflared -ErrorAction SilentlyContinue
      if ($service -and $service.Status -ne 'Running') {
        try { Start-Service -Name cloudflared; Write-Status 'Tunnel' 'service start requested' Cyan }
        catch { Write-Status 'Tunnel' 'service could not be started; local access remains available' Yellow }
      }
      $cloudflaredConfig = Join-Path $HOME '.cloudflared\config.yml'
      if (-not $service -and (Test-Path $cloudflaredConfig)) {
        $cloudflared = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
        $existingConnector = Get-Process cloudflared -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cloudflared -and -not $existingConnector) {
          Start-Process -FilePath $cloudflared.Source -ArgumentList '--config',$cloudflaredConfig,'tunnel','run' -WindowStyle Minimized | Out-Null
          Write-Status 'Tunnel' 'configured connector start requested' Cyan
        } elseif ($existingConnector) {
          Write-Status 'Tunnel' 'connector process already running; waiting for health' Yellow
        }
      }
      1..10 | ForEach-Object {
        if (-not $tunnelHealthy) { Start-Sleep -Seconds 1; $tunnelHealthy = Test-Tunnel }
      }
    }
    if ($tunnelHealthy) {
      Write-Status 'Tunnel' 'connected' Green
      $BrowserUrl = $env:MYNAS_PUBLIC_BASE_URL
    } else {
      Write-Status 'Tunnel' 'offline; local access remains available' Yellow
    }
  } else {
    Write-Status 'Tunnel' 'not configured; local access only' DarkGray
  }

  Write-Status 'Open' $BrowserUrl Cyan
  if (-not $NoBrowser) { Start-Process $BrowserUrl }
  exit 0
} catch {
  if ($FrontendStartedByLauncher -and $frontendProcess -and -not $frontendProcess.HasExited) {
    Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue
  }
  if ($BackendStartedByLauncher -and $backendProcess -and -not $backendProcess.HasExited) {
    Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
  }
  Write-Host "MyNAS startup failed: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
