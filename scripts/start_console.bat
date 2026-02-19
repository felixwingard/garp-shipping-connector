@echo off
REM Startar GARP Shipping Connector i konsolläge (för felsökning)
cd /d "%~dp0.."
python -m src --console
pause
