@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ======================================
echo   KMG Strategic Agent
echo ======================================
echo.
echo Выберите действие:
echo   1 - Собрать данные (Brent, KZT/USD, новости)
echo   2 - Рассчитать сценарии
echo   3 - Полный цикл (сбор + анализ + отчёты)
echo   4 - Только PPTX-отчёт
echo   5 - Выход
echo.
set /p choice="Введите номер (1-5): "

if "%choice%"=="1" (
    python -X utf8 main.py --collect
    pause
)
if "%choice%"=="2" (
    python -X utf8 main.py --analyze
    pause
)
if "%choice%"=="3" (
    python -X utf8 main.py --collect
    python -X utf8 main.py --analyze
    python -X utf8 main.py --report
    echo.
    echo Готово! Отчёт в папке reports\
    pause
)
if "%choice%"=="4" (
    python -X utf8 main.py --report
    echo.
    echo Готово! Отчёт в папке reports\
    start "" "%~dp0reports\"
    pause
)
if "%choice%"=="5" exit
