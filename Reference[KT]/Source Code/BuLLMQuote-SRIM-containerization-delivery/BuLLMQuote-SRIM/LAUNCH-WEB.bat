@echo off
REM Launches the accomplish-ui web frontend's dev server from its new location.
cd /d "%~dp0accomplish-ui"
pnpm --filter @accomplish/web dev
