@echo off
chcp 65001 >nul
title Laddar ner SumatraPDF
echo.
echo  Laddar ner SumatraPDF for PDF-utskrift...
echo.

cd /d "%~dp0.."

if exist "SumatraPDF.exe" (
    echo  SumatraPDF.exe finns redan!
    pause
    exit /b 0
)

echo  [1/2] Laddar ner zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Invoke-WebRequest -Uri 'https://www.sumatrapdfreader.org/dl/rel/3.5.2/SumatraPDF-3.5.2-64.zip' -OutFile 'SumatraPDF.zip' -UseBasicParsing"
if errorlevel 1 (
    echo  FEL: Nedladdning misslyckades!
    echo  Ladda ner manuellt: sumatrapdfreader.org - 64-bit Portable
    pause
    exit /b 1
)
echo         Klart!
echo.

echo  [2/2] Packar upp...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -Path 'SumatraPDF.zip' -DestinationPath '.' -Force; $e = Get-ChildItem -Recurse -Filter 'SumatraPDF.exe' | Select-Object -First 1; if ($e) { Copy-Item $e.FullName -Destination 'SumatraPDF.exe' -Force }; Remove-Item 'SumatraPDF.zip' -Force -ErrorAction SilentlyContinue; Get-ChildItem -Directory -Filter 'SumatraPDF-*' | Remove-Item -Recurse -Force"
if errorlevel 1 (
    echo  FEL: Uppackning misslyckades!
    pause
    exit /b 1
)
echo         Klart!
echo.

if exist "SumatraPDF.exe" (
    echo  KLART! SumatraPDF.exe finns nu i projektmappen.
) else (
    echo  Oklart om det lyckades. Kontrollera manuellt.
)
echo.
pause
