@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo КМГ Telegram-бот запущен. Не закрывайте это окно.
echo Команды в Telegram: /status /analyze /news /report /help
echo.
python -X utf8 bot.py
pause
