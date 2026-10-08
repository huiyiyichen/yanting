@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_loreal_demo.ps1" -OpenBrowser %*
if errorlevel 1 (
    echo.
    echo Startup failed. Check the message above and data\runtime\logs.
    pause
    exit /b 1
)
exit /b 0
