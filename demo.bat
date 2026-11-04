@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 시연 모드를 시작합니다. 가짜 저장소와 가짜 GitLab/Jira/AWS 데이터로 동작하며 실제 시스템에는 접속하지 않습니다.
python --version >nul 2>&1
if errorlevel 1 (
  echo [오류] Python 을 찾을 수 없습니다. Python 3.10 이상을 설치한 뒤 다시 실행하세요.
  pause
  exit /b 1
)
python -c "import flask, requests, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo 필요한 패키지를 설치합니다...
  python -m pip install -r requirements.txt
)
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8090"
python demo_server.py --demo 8090
if errorlevel 1 pause
