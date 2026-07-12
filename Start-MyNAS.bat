@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set "MYNAS_EXIT=%ERRORLEVEL%"
if not "%MYNAS_EXIT%"=="0" pause
exit /b %MYNAS_EXIT%
