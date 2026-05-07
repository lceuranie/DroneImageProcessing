@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."

pushd "%PROJECT_ROOT%"
python -m src.viewer
if errorlevel 1 (
    popd
    exit /b 1
)

start "" "%PROJECT_ROOT%\data\visualization\viewer.html"
popd
endlocal
