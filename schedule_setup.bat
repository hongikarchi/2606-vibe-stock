@echo off
REM ============================================================================
REM schedule_setup.bat — register run_pipeline.bat in Windows Task Scheduler.
REM   Runs the quantitative data refresh 3x/day (08:00, 14:00, 20:00).
REM   Only runs when the PC is on; skips gracefully if Docker/Neo4j is off.
REM
REM   Run ONCE (as your normal user) to register.  Verify run_pipeline.bat works
REM   manually first.
REM
REM   Disable later:  schtasks /Delete /TN "StockKG\refresh-*" /F
REM   See status:     schtasks /Query  /TN "StockKG\refresh-08" /V
REM ============================================================================
setlocal
set "BAT=%~dp0run_pipeline.bat"

echo Registering 3x/day refresh for: %BAT%
echo.

REM /SC DAILY /ST HH:MM  — daily at the given time. /RL LIMITED = no admin needed.
schtasks /Create /TN "StockKG\refresh-08" /TR "\"%BAT%\"" /SC DAILY /ST 08:00 /RL LIMITED /F
schtasks /Create /TN "StockKG\refresh-14" /TR "\"%BAT%\"" /SC DAILY /ST 14:00 /RL LIMITED /F
schtasks /Create /TN "StockKG\refresh-20" /TR "\"%BAT%\"" /SC DAILY /ST 20:00 /RL LIMITED /F

echo.
echo Done. Tasks registered under "StockKG\" in Task Scheduler.
echo   - Runs only while the PC is on (no wake-from-sleep).
echo   - If Docker/Neo4j is off at run time, the batch logs a skip and exits cleanly.
echo   - Logs: logs\refresh.log
echo.
echo To run one now (test):   schtasks /Run /TN "StockKG\refresh-08"
echo To remove all:           schtasks /Delete /TN "StockKG\refresh-08" /F ^&^& schtasks /Delete /TN "StockKG\refresh-14" /F ^&^& schtasks /Delete /TN "StockKG\refresh-20" /F
endlocal
