@echo off
REM ============================================================================
REM run_pipeline.bat — quantitative data refresh (2-tier: the [Q] automatable pass)
REM   Windows Task Scheduler runs this 2-3x/day. Refreshes news/prices/themes,
REM   regenerates the React artifacts, and pushes to GitHub (Pages auto-redeploys).
REM   The [S] meaning layer (theme summaries) is NOT touched here — session does that.
REM
REM Manual run:  double-click, or  run_pipeline.bat
REM Requires:    Docker Desktop running (Neo4j), gh auth configured.
REM ============================================================================
setlocal
cd /d "%~dp0"

set LOG=logs\refresh.log
if not exist logs mkdir logs
echo. >> "%LOG%"
echo ==================== %DATE% %TIME% ==================== >> "%LOG%"

REM --- 1. Neo4j reachable? (Docker may be off even if PC is on) -------------
docker ps --filter "name=skg-neo4j" --filter "status=running" --format "{{.Names}}" | findstr skg-neo4j >nul 2>&1
if errorlevel 1 (
  echo [skip] Neo4j container not running ^(start Docker Desktop^) >> "%LOG%"
  echo [skip] Neo4j not running - aborting refresh
  exit /b 0
)

set "PYTHONIOENCODING=utf-8"
set "SKG_STORAGE_BACKEND=neo4j"

REM --- advance the "current" instant to the run date so the published freshness label tracks
REM the data instead of drifting stale. (Python date formatting is locale-safe; batch's is not.) -
for /f %%d in ('python -c "import datetime;print(datetime.date.today().isoformat()+'T00:00:00')"') do set "SKG_AS_OF_NOW=%%d"
echo [env] SKG_AS_OF_NOW=%SKG_AS_OF_NOW% >> "%LOG%"

REM --- 2. quantitative pass (rule-based, idempotent) ------------------------
REM news (US). For KR news+DART set SKG_INCLUDE_KR=1 (heavier; e.g. once/day not 3x).
echo [run] news_pull >> "%LOG%"
python pipelines\news_pull.py        >> "%LOG%" 2>&1
if "%SKG_INCLUDE_KR%"=="1" (
  echo [run] kr_pull >> "%LOG%"
  python pipelines\kr_pull.py        >> "%LOG%" 2>&1
)
echo [run] market_state_pull >> "%LOG%"
python pipelines\market_state_pull.py >> "%LOG%" 2>&1
REM keep index-membership tags current (non-destructive; never auto-prunes in the cron) ----
echo [run] tag_universe >> "%LOG%"
python pipelines\tag_universe.py     >> "%LOG%" 2>&1
REM collapse duplicate news Claims/Mentions BEFORE counting (idempotent: keeps lowest claim_id
REM per content group, no-op once deduped). Stops the ~1.22x count inflation accumulating. ----
echo [run] dedup_news >> "%LOG%"
python pipelines\dedup_news.py       >> "%LOG%" 2>&1
echo [run] build_themes >> "%LOG%"
python pipelines\build_themes.py     >> "%LOG%" 2>&1
echo [run] build_emergent >> "%LOG%"
python pipelines\build_emergent.py   >> "%LOG%" 2>&1
echo [run] reanalyze >> "%LOG%"
python pipelines\reanalyze.py        >> "%LOG%" 2>&1
echo [run] build_theme_view ^(ThemeDay buckets^) >> "%LOG%"
python pipelines\build_theme_view.py >> "%LOG%" 2>&1
echo [run] export_artifacts >> "%LOG%"
python pipelines\export_artifacts.py >> "%LOG%" 2>&1

REM --- 3. commit + push only if the app data actually changed ----------------
git add web/public/data >> "%LOG%" 2>&1
git diff --cached --quiet web/public/data
if errorlevel 1 (
  echo [git] data changed - committing + pushing >> "%LOG%"
  git -c core.autocrlf=false commit -q -m "[auto] data refresh %DATE%" >> "%LOG%" 2>&1
  git push >> "%LOG%" 2>&1
  echo [git] pushed - GitHub Pages will redeploy >> "%LOG%"
) else (
  echo [git] no data change - skip commit >> "%LOG%"
)

echo [done] %DATE% %TIME% >> "%LOG%"
endlocal
