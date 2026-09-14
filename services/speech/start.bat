@echo off
REM Launch the local speech stack (ASR + TTS) on Windows.
REM SenseVoice ASR is served from this folder; IndexTTS2 from its own checkout.
setlocal
set HERE=%~dp0
set INDEX_TTS_VENV=D:\项目\index-tts\.venv
set ASR_VENV=%HERE%venv

REM Pick the first python that can import uvicorn + funasr.
REM The local ASR venv is sometimes incomplete, so fall back to the
REM IndexTTS2 venv where funasr was installed on this machine.
set PY=
for %%P in ("%ASR_VENV%\Scripts\python.exe" "%INDEX_TTS_VENV%\Scripts\python.exe" python) do (
  if exist %%P (
    %%P -c "import uvicorn, funasr" >nul 2>&1
    if not errorlevel 1 (
      set PY=%%P
      goto :found
    )
  )
)
:found
if not defined PY (
  echo ERROR: no python with uvicorn+funasr found
  exit /b 1
)

echo Starting SenseVoice ASR on :8000 ...
start "" "%PY%" -m uvicorn sensevoice_asr_server:app --host 0.0.0.0 --port 8000 --log-level info

echo Starting IndexTTS2 TTS on :8765 ...
start "" "%INDEX_TTS_VENV%\Scripts\python.exe" -m uvicorn tts_server:app --host 0.0.0.0 --port 8765 --log-level info --app-dir "D:\项目\index-tts"

echo Speech stack launching. Press any key to stop all...
pause >nul
taskkill /IM uvicorn.exe /F >nul 2>&1
endlocal
