@echo off
rem Doppio clic: apre la Guida nel browser (cronometro, acquisizioni, analisi, file per la centralina)
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m dvtool guida) || (python -m dvtool guida)
pause
