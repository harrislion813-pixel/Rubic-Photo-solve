@echo off
chcp 65001 >nul
cd /d "%~dp0"
RubicPhotoSolve.exe
if errorlevel 1 (
  echo.
  echo 启动失败。请保留此窗口并将以上错误信息提供给维护者。
  pause
)
