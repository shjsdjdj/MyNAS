@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Manage-MyNASStartup.ps1" -Action Disable
if errorlevel 1 pause
