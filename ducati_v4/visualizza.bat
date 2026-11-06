@echo off
rem Apre il visualizzatore sulla cartella indicata (default: privato\progetto)
cd /d "%~dp0"
set CARTELLA=%~1
if "%CARTELLA%"=="" set CARTELLA=privato\progetto
where py >nul 2>nul && (py -3 -m dvtool visualizza "%CARTELLA%") || (python -m dvtool visualizza "%CARTELLA%")
