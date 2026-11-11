@echo off
rem Windows launcher; the work is done by start.py (the same on Linux/macOS, via start.sh).
rem
rem   start              checks, installs anything missing, migrates the database, starts the API and web dev server
rem   start --check      checks only; starts nothing
rem   start --setup      installs, migrates and builds the web app; starts nothing
rem   start --serve      runs the built app as one process, the way the Windows service does
rem
rem Uses the Python launcher (py) when it's installed, otherwise python on PATH.
setlocal
where py >nul 2>nul && (py -3 "%~dp0start.py" %* & exit /b)
python "%~dp0start.py" %*
