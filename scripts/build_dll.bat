@echo off
setlocal
cd /d "%~dp0\.."
python scripts\build_dll.py %*
if errorlevel 1 exit /b %errorlevel%
echo.
echo DLL search path: build\Release\SRDBridge.dll
endlocal
