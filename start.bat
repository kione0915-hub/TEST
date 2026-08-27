@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  자동매매 대시보드를 준비하는 중입니다...
echo  (처음 한 번은 설치 때문에 시간이 걸립니다)
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [오류] Python 이 설치되어 있지 않습니다.
    echo https://python.org/downloads 에서 설치하세요.
    echo 설치할 때 "Add Python to PATH" 를 꼭 체크하세요!
    pause
    exit /b 1
)

python -m pip install -r requirements.txt --quiet
python webapp.py
pause
