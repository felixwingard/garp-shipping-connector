@echo off
chcp 65001 >nul
title GARP Shipping Connector — Installation
echo.
echo  ============================================
echo   GARP Shipping Connector — Installation
echo  ============================================
echo.

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
if "%PYTHON%"=="py" (set PYTHONW=pyw) else (set PYTHONW=pythonw)

echo  [1/4] Installerar Python-paket...
%PYTHON% -m pip install requests watchdog pyyaml pywin32 pystray Pillow >nul 2>&1
echo         Klart!
echo.

echo  [2/4] Skapar mappar...
if not exist "C:\GARP\Unifaun\Outgoing" mkdir "C:\GARP\Unifaun\Outgoing"
if not exist "C:\GARP\Unifaun\Done" mkdir "C:\GARP\Unifaun\Done"
if not exist "C:\GARP\Unifaun\Error" mkdir "C:\GARP\Unifaun\Error"
if not exist "C:\GARP\Logs" mkdir "C:\GARP\Logs"
if not exist "C:\GARP\Labels" mkdir "C:\GARP\Labels"
echo         Klart!
echo.

echo  [3/4] Skapar konfiguration...
if not exist "config\config.yaml" (
    copy "config\config.example.yaml" "config\config.yaml" >nul

    REM Satt tomma SMTP-varden sa programmet inte kraschar
    powershell -Command "(Get-Content 'config\config.yaml') -replace '\$\{SMTP_USERNAME\}', '' | Set-Content 'config\config.yaml'"
    powershell -Command "(Get-Content 'config\config.yaml') -replace '\$\{SMTP_PASSWORD\}', '' | Set-Content 'config\config.yaml'"
    powershell -Command "(Get-Content 'config\config.yaml') -replace '\$\{SMTP_FROM_ADDRESS\}', '' | Set-Content 'config\config.yaml'"
    powershell -Command "(Get-Content 'config\config.yaml') -replace '\$\{SENDER_EMAIL\}', '' | Set-Content 'config\config.yaml'"

    echo         config.yaml skapad - fyll i DHL_API_KEY i config!
) else (
    echo         config.yaml finns redan, behaller befintlig.
)
echo.

echo  [4/4] Skapar genvag pa skrivbordet...
powershell -Command "$WshShell = New-Object -ComObject WScript.Shell; $Shortcut = $WshShell.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'GARP Shipping.lnk')); $Shortcut.TargetPath = '%PYTHONW%'; $Shortcut.Arguments = '-m src'; $Shortcut.WorkingDirectory = '%CD%'; $Shortcut.Description = 'GARP Shipping Connector'; $Shortcut.Save()"
echo         Klart!
echo.

echo  ============================================
echo   INSTALLATIONEN KLAR!
echo  ============================================
echo.
echo   Fyll i config\config.yaml med era API-nycklar
echo   (eller sat miljovariablerna innan start)
echo.
echo   Starta programmet:
echo     - Dubbelklicka "GARP Shipping" pa skrivbordet
echo     - Eller kor: python -m src
echo.
echo   Testa i konsollage (ser loggen):
echo     python -m src --console
echo.
echo   Skrivare valjs via hogerklick pa tray-ikonen
echo   (den grona cirkeln nere vid klockan)
echo.
pause
