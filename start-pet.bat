@echo off
chcp 65001 >nul
title AIJADE - Desktop Pet Mode
setlocal

REM === paths and runtime ===
set "NODEJS_DIR=C:\Users\Administrator\AppData\Local\Programs\nodejs"
set "NPM_GLOBAL=C:\Users\Administrator\AppData\Roaming\npm"
set "OLLAMA_DIR=C:\Users\Administrator\AppData\Local\Programs\Ollama"

if exist "%NODEJS_DIR%" set "PATH=%NODEJS_DIR%;%NPM_GLOBAL%;%PATH%"
if exist "%OLLAMA_DIR%" set "PATH=%OLLAMA_DIR%;%PATH%"

REM git PATH is handled inside the PowerShell launch step below (prepended to
REM $env:PATH there). The build plugin "unplugin-info" shells out to git; when
REM launched by double-click, git (WorkBuddy's PortableGit) is usually NOT on PATH,
REM so we add it in PowerShell BEFORE running pnpm dev. (Setting it in cmd first and
REM expecting it to reach the PowerShell child was unreliable, and the old cmd
REM "for" loop also broke on the "(x86)" parentheses.)
REM Clear injected debug flags that may break Vite/Electron prebuild.

REM Clear injected debug flags that may break Vite/Electron prebuild.
set "NODE_OPTIONS="

REM IMPORTANT: ELECTRON_RUN_AS_NODE must be truly removed from the env (not just
REM empty). Electron's C++ uses getenv() and treats an empty string as "set",
REM which makes `import { BrowserWindow } from 'electron'` fail. We unset it in
REM PowerShell below before launching.

set "LOG=E:\AIJADE\start_pet_lastrun.log"
echo [pet] %date% %time% begin > "%LOG%"

echo ============================================
echo  AIJADE Desktop Pet Mode
echo  Location: E:\AIJADE
echo ============================================
echo.

REM === check Node.js ===
where node >nul 2>nul || (
  echo [ERR] Node.js not found! Check PATH or reinstall Node.js.
  goto :end
)
echo [OK] node found

REM === ensure local LLM (Ollama) is up ===
echo [*] Checking Ollama on :11434 ... >> "%LOG%"
curl -s -m 3 http://localhost:11434/api/version >nul 2>nul
if errorlevel 1 (
  echo [*] Ollama not running, starting via scheduled task ...
  schtasks /run /tn OllamaServe >nul 2>&1
  timeout /t 10 /nobreak >nul
) else (
  echo [OK] Ollama already up
)
ollama list 2>nul | findstr /i "qwythos-9b" >nul && (
  echo [OK] qwythos-9b present
) || (
  echo [*] Importing Qwythos GGUF ...
  ollama create qwythos-9b -f E:\AIJADE\services\local-llm\Modelfile.qwythos-local
)
echo [*] LLM ready: http://localhost:11434/v1  model=qwythos-9b
echo.

REM === launch desktop pet (Electron) ===
echo [*] Launching AIJADE Desktop Pet (Electron) ...
echo     This opens an Electron window.
echo     Use the control island at bottom-right to open pet mode.
echo     Close that window to exit pet mode.
echo ============================================
echo.

REM Unset ELECTRON_RUN_AS_NODE via PowerShell, then start dev.
REM All output (including any Electron crash trace) is saved to start_pet_dev.log
REM and also mirrored to this window. The window stays open at the end (pause)
REM so you can copy the crash log instead of it flashing away.
cd /d E:\AIJADE
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:ELECTRON_RUN_AS_NODE=$null; @(($env:USERPROFILE + '\.workbuddy\vendor\PortableGit\mingw64\bin'),($env:USERPROFILE + '\.workbuddy\vendor\PortableGit\cmd'),($env:USERPROFILE + '\.workbuddy\vendor\PortableGit\usr\bin'),'C:\Program Files\Git\cmd','C:\Program Files\Git\bin','C:\Program Files (x86)\Git\cmd') | ForEach-Object { if (Test-Path ($_ + '\git.exe')) { $env:PATH = ($_ + ';' + $env:PATH) } }; $ErrorActionPreference='SilentlyContinue'; pnpm.cmd --filter @proj-aijade/stage-tamagotchi dev 2>&1 | Tee-Object -FilePath 'E:\AIJADE\start_pet_dev.log'"

echo.
echo [pet] dev exited. See E:\AIJADE\start_pet_dev.log for details.
pause

:end
endlocal
