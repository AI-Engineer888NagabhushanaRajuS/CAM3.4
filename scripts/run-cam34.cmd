@echo off
rem Double-click or run from any shell: builds/starts CAM 3.4 (see run-cam34.ps1 for options: -Build -Status -Stop).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-cam34.ps1" %*
