@echo off
REM PLACEHOLDER -- only the frontend (accomplish-ui) is populated in this repo so far.
REM Backend/mcp-tools/database/deployment are empty placeholders (see their README.md
REM files) and a real install script can't do anything useful for them yet.

echo Installing accomplish-ui dependencies...
cd /d "%~dp0accomplish-ui"
call pnpm install
echo.
echo Done. Backend/mcp-tools installation is not yet implemented -- see README.md.
