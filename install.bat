@echo off
echo === Установка КМГ Strategic Agent ===
echo.

:: Проверка Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ОШИБКА] Python не найден!
    echo Скачайте Python 3.11+ с https://www.python.org/downloads/
    echo При установке ОБЯЗАТЕЛЬНО отметьте "Add Python to PATH"
    pause
    exit /b 1
)

echo [OK] Python найден:
python --version

echo.
echo Установка зависимостей...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo === Установка завершена ===
echo Запустите настройку: python main.py --setup
echo.
pause
