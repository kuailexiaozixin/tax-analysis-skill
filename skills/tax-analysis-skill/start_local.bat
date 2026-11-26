@echo off
REM ============================================================
REM ASCII-only launcher: avoids cmd code-page parsing issues.
REM Keep this file ASCII with CRLF line endings.
REM ============================================================
cd /d "%~dp0"

echo ============================================
echo  Tax Policy Search Engine - Local
echo ============================================
echo.

echo Checking Python...
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Install Python 3 first.
    pause
    exit /b 1
)

echo Installing / checking dependencies...
python -m pip install -r requirements.txt -q

REM Port follows tax_server.py: default 5080 unless TAX_PORT is set.
set PORT=5080
if not "%TAX_PORT%"=="" set PORT=%TAX_PORT%

echo.
echo Starting server on port %PORT%...

REM If already running, open the browser without starting a second server.
REM ProgressPreference suppresses Invoke-WebRequest progress output.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; try{ if((Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/api/health' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200){exit 0} }catch{}; exit 1"
if %ERRORLEVEL% equ 0 (
    echo Server is already running. Opening browser.
    start "" http://127.0.0.1:%PORT%
    goto :done
)

REM Start the server in a separate window; closing that window stops it.
REM tax_server.py sets its own console code page, so no nested cmd /k is needed.
REM Bind address follows tax_server.py TAX_BIND (default 127.0.0.1, local only).
start "tax-analysis-skill server" python scripts\tax_server.py

REM Wait for the port before opening the browser.
REM Each failed probe can take about 1.5 seconds; 40 probes allow about 1 minute.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; $ok=$false; for($i=0;$i -lt 40;$i++){ try{ if((Invoke-WebRequest -Uri 'http://127.0.0.1:%PORT%/api/health' -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200){$ok=$true; break} }catch{}; Start-Sleep -Milliseconds 500 }; if($ok){exit 0}else{exit 1}"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [WARNING] Server did not become ready within about 1 minute. Opening browser anyway.
    echo         Check the "tax-analysis-skill server" window for errors.
    echo.
)

start "" http://127.0.0.1:%PORT%

:done
echo.
echo Server is running in the separate "tax-analysis-skill server" window.
echo To stop it, close that window.
echo.
pause
