@echo off
REM Lägger till GARP Shipping Connector i Windows Autostart
REM Kör som Administratör

set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set SCRIPT_DIR=%~dp0

echo Skapar genvag i Autostart...
echo Set oWS = WScript.CreateObject("WScript.Shell") > "%TEMP%\shortcut.vbs"
echo sLinkFile = "%STARTUP_DIR%\GARP Shipping Connector.lnk" >> "%TEMP%\shortcut.vbs"
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> "%TEMP%\shortcut.vbs"
echo oLink.TargetPath = "%SCRIPT_DIR%start.bat" >> "%TEMP%\shortcut.vbs"
echo oLink.WorkingDirectory = "%SCRIPT_DIR%.." >> "%TEMP%\shortcut.vbs"
echo oLink.WindowStyle = 7 >> "%TEMP%\shortcut.vbs"
echo oLink.Description = "GARP Shipping Connector" >> "%TEMP%\shortcut.vbs"
echo oLink.Save >> "%TEMP%\shortcut.vbs"

cscript //nologo "%TEMP%\shortcut.vbs"
del "%TEMP%\shortcut.vbs"

echo.
echo Klart! GARP Shipping Connector startar automatiskt vid inloggning.
echo Genvag skapad i: %STARTUP_DIR%
echo.
pause
