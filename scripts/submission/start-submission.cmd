@echo off
setlocal
uv run --no-project --python 3.11 "%~dp0prepare_submission.py"
if errorlevel 1 (
    pause
    exit /b 1
)
call "%~dp0code\start-demo.cmd" %*
exit /b %errorlevel%
