@echo off
chcp 65001 >nul
title GARP Shipping Connector — Debug-bygg
echo.
echo  Bygger DEBUG-version (med konsolfönster för felsökning)
echo.

cd /d "%~dp0.."
python -m pip install pyinstaller pywin32 --quiet 2>nul

REM Temporär spec med console=True (visar logg i fönster)
copy build\build.spec build\build_debug.spec >nul
powershell -Command "$c = Get-Content 'build\build.spec' -Raw; $c = $c -replace 'console=False', 'console=True' -replace \"name='GarpShippingConnector'\", \"name='GarpShippingConnector-debug'\"; Set-Content 'build\build_debug.spec' $c"

pyinstaller build/build_debug.spec --noconfirm --clean
del build\build_debug.spec 2>nul

echo.
echo  Klart! dist\GarpShippingConnector-debug.exe
echo  Kör den för att se logg i ett konsolfönster.
echo.
pause
