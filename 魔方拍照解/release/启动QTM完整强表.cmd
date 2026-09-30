@echo off
chcp 65001 >nul
cd /d "%~dp0"
set CUBE_QTM_ASSET_PROFILE=strong
set CUBE_QTM_STRONG_FORMAT=nibble
set CUBE_NATIVE_ASSET_LOADING=eager
echo QTM full assets will be verified before search. First initialization may take several seconds.
RubicPhotoSolve.exe
if errorlevel 1 pause
