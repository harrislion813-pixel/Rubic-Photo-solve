@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify_installation.ps1" -Root "%~dp0."
if errorlevel 1 echo Installation verification failed.
pause
