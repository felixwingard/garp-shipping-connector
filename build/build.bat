@echo off
chcp 65001 >nul
title GARP Shipping Connector — Bygg .exe
echo.
echo  ============================================
echo   Bygger GARP Shipping Connector
echo  ============================================
echo.

REM Körandes från build/ — gå till projektrot
cd /d "%~dp0.."

REM Kontrollera Python (prova python eller py-launcher)
set PYTHON=python
python --version >nul 2>&1
if errorlevel 1 (
    py --version >nul 2>&1
    if errorlevel 1 (
        echo  FEL: Python hittades inte!
        echo  Installera fran python.org — kryssa i "Add Python to PATH"
        pause
        exit /b 1
    )
    set PYTHON=py
)

echo  [1/3] Installerar PyInstaller...
%PYTHON% -m pip install pyinstaller pywin32 --quiet
echo.

echo  [2/3] Bygger .exe (kan ta 1-2 minuter)...
%PYTHON% -m PyInstaller build/build.spec --noconfirm --clean
if errorlevel 1 (
    echo  FEL: Bygget misslyckades
    pause
    exit /b 1
)
echo.

echo  [3/3] Skapar installationspaket...
set "EXE=dist\GarpShippingConnector.exe"
set "PACKAGE=dist\GARP-Shipping-Connector"
set INSTALL_BAT=Install-GARP-Shipping.bat

if not exist "%PACKAGE%" mkdir "%PACKAGE%"
if not exist "%PACKAGE%\config" mkdir "%PACKAGE%\config"

copy /Y "%EXE%" "%PACKAGE%\" >nul
copy /Y "config\config.example.yaml" "%PACKAGE%\config\" >nul

REM Skapa Install.bat för paketet
(
echo @echo off
echo chcp 65001 ^>nul
echo title GARP Shipping Connector — Installation
echo.
echo echo  Skapar mappar...
echo if not exist "C:\GARP\Unifaun\Outgoing" mkdir "C:\GARP\Unifaun\Outgoing"
echo if not exist "C:\GARP\Unifaun\Done" mkdir "C:\GARP\Unifaun\Done"
echo if not exist "C:\GARP\Unifaun\Error" mkdir "C:\GARP\Unifaun\Error"
echo if not exist "C:\GARP\Logs" mkdir "C:\GARP\Logs"
echo if not exist "C:\GARP\Labels" mkdir "C:\GARP\Labels"
echo.
echo if not exist "config\config.yaml" ^(
echo     copy "config\config.example.yaml" "config\config.yaml" ^>nul
echo     echo  config.yaml skapad — redigera med era uppgifter!
echo ^) else ^(
echo     echo  config.yaml finns redan.
echo ^)
echo.
echo echo  Skapar genvåg på skrivbordet...
echo powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\GARP Shipping.lnk'); $Shortcut.TargetPath = '%CD%\GarpShippingConnector.exe'; $Shortcut.WorkingDirectory = '%CD%'; $Shortcut.Description = 'GARP Shipping Connector'; $Shortcut.Save()"
echo.
echo echo  Klart! Starta GarpShippingConnector.exe
echo echo  eller dubbelklicka "GARP Shipping" på skrivbordet.
echo pause
) > "%PACKAGE%\%INSTALL_BAT%"

echo.
echo  ============================================
echo   KLART!
echo  ============================================
echo.
echo   Paket: %PACKAGE%\
echo   - GarpShippingConnector.exe
echo   - config\config.example.yaml
echo   - %INSTALL_BAT%
echo.
echo   Distribuera: Zippa mappen och skicka till användare.
echo   Användare: Packa upp, kör %INSTALL_BAT%, redigera config.yaml.
echo.
pause
