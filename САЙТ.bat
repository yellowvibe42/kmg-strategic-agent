@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo Запуск КМГ Dashboard...
echo Сайт откроется автоматически: http://localhost:5000
echo Не закрывайте это окно.
echo.
python -X utf8 server.py
pause
