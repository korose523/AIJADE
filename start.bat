@echo off
chcp 65001 >nul 2>nul
title AIJADE - AI Virtual Companion
set "NODEJS_DIR=C:\Users\Administrator\AppData\Local\Programs\nodejs"
set "NPM_GLOBAL=C:\Users\Administrator\AppData\Roaming\npm"
set "OLLAMA_DIR=C:\Users\Administrator\AppData\Local\Programs\Ollama"
if exist "%NODEJS_DIR%" set "PATH=%PATH%;%NODEJS_DIR%"
if exist "%NPM_GLOBAL%" set "PATH=%PATH%;%NPM_GLOBAL%"
if exist "%OLLAMA_DIR%" set "PATH=%PATH%;%OLLAMA_DIR%"
set "NODE_OPTIONS="
set "LOG=E:\AIJADE\start_lastrun.log"
echo [%date% %time%] AIJADE start.bat begin > "%LOG%"

echo ============================================
echo  AIJADE Project v0.10.2
echo  Location: E:\AIJADE
echo ============================================
echo.
echo  Choose LLM backend:
echo    [1] Local LLM (Ollama + Qwythos-9B on :11434)
echo    [2] Cloud API (DashScope, OpenAI, etc.)
echo.
set "choice=1"
set /p choice=Enter choice [1-2] (default 1):
set "choice=%choice: =%"
echo [%date% %time%] choice=%choice% >> "%LOG%"

where node >nul 2>nul || (
  echo [ERR] Node.js not found! Check PATH or reinstall Node.js. >> "%LOG%"
  echo [ERR] Node.js not found! Check PATH or reinstall Node.js.
  goto :end
)
echo [OK] node found >> "%LOG%"

where pnpm >nul 2>nul || (
  echo [*] pnpm missing, installing pnpm@10.33.0 ... >> "%LOG%"
  call npm install -g pnpm@10.33.0 >> "%LOG%" 2>&1
)
echo [OK] pnpm: >> "%LOG%"
where pnpm >> "%LOG%" 2>&1

if "%choice%"=="1" (
  echo [*] Checking Ollama on :11434 ... >> "%LOG%"
  curl -s -m 3 http://localhost:11434/api/version >nul 2>nul
  if errorlevel 1 (
    echo [*] Ollama not running, starting via scheduled task ... >> "%LOG%"
    schtasks /run /tn OllamaServe >> "%LOG%" 2>&1
    timeout /t 10 /nobreak >nul
  ) else (
    echo [OK] Ollama already up >> "%LOG%"
  )
  ollama list 2>nul | findstr /i "qwythos-9b" >nul && (
    echo [OK] qwythos-9b present >> "%LOG%"
  ) || (
    echo [*] Importing Qwythos GGUF ... >> "%LOG%"
    ollama create qwythos-9b -f E:\AIJADE\services\local-llm\Modelfile.qwythos-local >> "%LOG%" 2>&1
  )
  echo [*] LLM ready: http://localhost:11434/v1  model=qwythos-9b >> "%LOG%"
)

echo.
echo [*] Starting AIJADE Server ...
echo    Web:  http://localhost:5173
echo ============================================
echo [start] pnpm dev
cd /d E:\AIJADE
call pnpm dev
echo [end] pnpm dev exited code=%ERRORLEVEL% >> "%LOG%"

:end
echo.
echo === AIJADE finished. Log: %LOG% ===
pause
