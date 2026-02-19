@echo off
REM ============================================================
REM GARP Shipping Connector — Installation på lagerdator
REM ============================================================
REM Kör detta script som Administratör på lagerdatorn.
REM
REM Förutsättningar:
REM   - Python 3.9+ installerat (python.org)
REM   - SumatraPDF installerat (för PDF-utskrift)
REM   - Zebra-skrivare installerad i Windows
REM ============================================================

echo.
echo ========================================
echo  GARP Shipping Connector — Installation
echo ========================================
echo.

REM Kontrollera Python
python --version >nul 2>&1
if errorlevel 1 (
    echo FEL: Python hittades inte!
    echo Installera Python 3.9+ fran python.org
    echo Se till att kryssa i "Add Python to PATH"
    pause
    exit /b 1
)

echo [1/5] Python hittad:
python --version
echo.

REM Installera beroenden
echo [2/5] Installerar Python-beroenden...
pip install requests watchdog pyyaml pywin32 pystray Pillow
if errorlevel 1 (
    echo VARNING: Nagra beroenden kunde inte installeras
)
echo.

REM Skapa mappar
echo [3/5] Skapar mappar...
if not exist "C:\GARP\Unifaun\Outgoing" mkdir "C:\GARP\Unifaun\Outgoing"
if not exist "C:\GARP\Unifaun\Done" mkdir "C:\GARP\Unifaun\Done"
if not exist "C:\GARP\Unifaun\Error" mkdir "C:\GARP\Unifaun\Error"
if not exist "C:\GARP\Logs" mkdir "C:\GARP\Logs"
if not exist "C:\GARP\Labels" mkdir "C:\GARP\Labels"
echo   C:\GARP\Unifaun\Outgoing  (GARP droppar XML har)
echo   C:\GARP\Unifaun\Done      (klara filer)
echo   C:\GARP\Unifaun\Error     (felfiler)
echo   C:\GARP\Logs              (loggfiler)
echo   C:\GARP\Labels            (etikettbackup)
echo.

REM Kopiera config
echo [4/5] Forbereder konfiguration...
if not exist "config\config.yaml" (
    copy "config\config.example.yaml" "config\config.yaml"
    echo   config.yaml skapad fran exempelfil.
    echo   *** VIKTIGT: Redigera config\config.yaml med ratta varden! ***
) else (
    echo   config.yaml finns redan — behaller befintlig.
)
echo.

REM Kontrollera SumatraPDF
echo [5/5] Kontrollerar SumatraPDF...
where SumatraPDF.exe >nul 2>&1
if errorlevel 1 (
    echo VARNING: SumatraPDF hittades inte i PATH.
    echo Installera fran: https://www.sumatrapdfreader.com
    echo Eller lagg till installationsmappen i PATH.
) else (
    echo   SumatraPDF hittad.
)

echo.
echo ========================================
echo  Installation klar!
echo ========================================
echo.
echo Nasta steg:
echo   1. Redigera config\config.yaml:
echo      - Satt DHL_API_KEY som miljovariabler (eller skriv in direkt)
echo      - Satt SMTP-uppgifter
echo      - Kontrollera skrivarnamn
echo.
echo   2. Testa med:
echo      python -m src --console
echo.
echo   3. Kor normalt med tray-ikon:
echo      python -m src
echo.
echo   4. (Valfritt) Bygg .exe:
echo      pip install pyinstaller
echo      pyinstaller build/build.spec
echo.
pause
