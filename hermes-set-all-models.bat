@echo off
setlocal EnableExtensions
REM Model settings now have ONE source: Hermes Model Router UI/backend.
REM The original editable BAT is backed up before installation.
REM No model values are stored or applied from this compatibility shortcut.
if /I "%~1"=="/dry-run" (
    echo Model Router shortcut: opens hermes://model-router; no configuration writes.
    exit /b 0
)
if /I "%~1"=="--dry-run" (
    echo Model Router shortcut: opens hermes://model-router; no configuration writes.
    exit /b 0
)
start "" "hermes://model-router"
if errorlevel 1 (
    echo Unable to open Hermes. Open Desktop and select Models and Routing.
    exit /b 1
)
exit /b 0
