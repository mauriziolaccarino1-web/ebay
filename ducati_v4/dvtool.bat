@echo off
rem Avvio rapido su Windows: dvtool.bat <comando> ...   (es. dvtool.bat demo --apri)
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m dvtool %*) || (python -m dvtool %*)
