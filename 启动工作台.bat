@echo off
cd /d %~dp0

rem 复盘工作台快捷启动：已在运行则直接打开浏览器，否则启动服务后再打开
rem 注意：PATH 里排前的 python 可能是 uv/Store 的隔离解释器（无 Flask），
rem 因此优先用确定装有 Flask 的绝对路径解释器，其余仅作兜底。

set "PY="
set "PYARGS="
if exist "C:\Users\kense\AppData\Local\Programs\Python\Python313\python.exe" set "PY=C:\Users\kense\AppData\Local\Programs\Python\Python313\python.exe"
if not defined PY where py >nul 2>&1 && set "PY=py" && set "PYARGS=-3"
if not defined PY set "PY=python"

rem —— 已在运行：直接打开浏览器 ——
netstat -ano | findstr /c:":8787" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    start "" "http://127.0.0.1:8787/mood"
    exit /b 0
)

echo 正在启动复盘工作台（窗口已最小化，关闭它=停止服务）...
start "workbench-webapp" /min "%PY%" %PYARGS% webapp\app.py

rem —— 轮询端口，最长约 15 秒 ——
set /a i=0
:waitloop
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr /c:":8787" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto opened
set /a i+=1
if %i% lss 15 goto waitloop

echo [错误] 服务未能启动，解释器=%PY%，请把最小化窗口里的报错发给 AI。
pause
exit /b 1

:opened
start "" "http://127.0.0.1:8787/mood"
exit /b 0
