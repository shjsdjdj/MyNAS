param(
  [Parameter(Mandatory = $true)]
  [ValidateSet('Enable', 'Disable')]
  [string]$Action
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StartupFolder = [Environment]::GetFolderPath('Startup')
$ShortcutPath = Join-Path $StartupFolder 'MyNAS.lnk'

if ($Action -eq 'Disable') {
  if (Test-Path $ShortcutPath) { Remove-Item -LiteralPath $ShortcutPath -Force }
  Write-Host 'MyNAS startup is disabled for the current Windows user.' -ForegroundColor Green
  exit 0
}

$PowerShell = (Get-Process -Id $PID).Path
$StartScript = Join-Path $Root 'start.ps1'
if (-not (Test-Path $StartScript)) { throw "MyNAS start script was not found: $StartScript" }
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $PowerShell
$Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$StartScript`" -NoBrowser"
$Shortcut.WorkingDirectory = $Root
$Shortcut.Description = 'Start MyNAS for the current Windows user'
$Shortcut.WindowStyle = 7
$Shortcut.Save()
Write-Host "MyNAS startup is enabled for the current Windows user: $ShortcutPath" -ForegroundColor Green
