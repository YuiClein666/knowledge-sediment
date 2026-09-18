@echo off
rem kb - knowledge-sediment command entry (Windows)
setlocal EnableExtensions EnableDelayedExpansion
set "ROOT=%~dp0"
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE (
  where python >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
  echo [kb] Python not found. Install Python 3.9+ first: https://www.python.org/downloads/
  exit /b 1
)
"!PYEXE!" -X utf8 "%ROOT%scripts\kb.py" %*
exit /b !errorlevel!
