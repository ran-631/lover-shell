@echo off
chcp 65001 >nul

title 电脑控制

echo ===================================
echo     电脑控制
echo  恋人在 Kelivo 打开「电脑」即可控制
echo  日志: %~dp0logs\
echo  数据: %~dp0data\
echo ===================================
echo.
echo  📡 正在连接云端...
echo.

cd /d "%~dp0"
"C:\Users\HW\AppData\Local\Python\pythoncore-3.14-64\python.exe" app.py
if errorlevel 1 (
    echo.
    echo [!] 启动失败
    pause
)