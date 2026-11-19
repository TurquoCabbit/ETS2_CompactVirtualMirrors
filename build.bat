@echo off
setlocal
pushd "%~dp0" || exit /b 1
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m mirrors.cli %*
) else (
    python -m mirrors.cli %*
)
set "result=%errorlevel%"
popd
exit /b %result%
