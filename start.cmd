@echo off
REM Double-click to start win-translate in the background.
REM cd first: "-m wintranslate" resolves the package from the working directory.
REM pythonw.exe (not python.exe) so no console window is left behind.
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m wintranslate
