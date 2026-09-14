@echo off
title AIJADE Amber HE 智能音箱模式
echo ============================================
echo  AIJADE + 琥珀 HE 全息智能音箱
echo  唤醒词: 你好小爱 / 嘿AIRI / 小爱同学
echo ============================================
echo.

REM 确保 pnpm 所在目录在 PATH 中
set "PATH=%APPDATA%\npm;C:\Users\Administrator\.workbuddy\binaries\node\versions\22.22.2;%PATH%"

echo [1] 确保 Ollama 运行中...
echo [2] 启动 AIRI 开发服务器...
echo [3] 在琥珀 HE 浏览器打开:
echo     http://你的电脑IP:5173/?hologram=1
echo.
echo 按任意键启动...
pause >nul

cd /d "H:\AIJADE"

REM 优先用 pnpm，找不到则回退 npx vite
where pnpm >nul 2>&1
if %errorlevel%==0 (
    pnpm dev
) else (
    echo [提示] pnpm 未找到，使用 npx vite 启动...
    npx vite --host --port 5173
)

pause
