@echo off
chcp 65001 >nul
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo [오류] Python 을 찾을 수 없습니다. Python 3.10 이상을 설치하세요.
  echo        설치 화면에서 "Add python.exe to PATH" 에 반드시 체크해야 합니다.
  pause
  exit /b 1
)

python -c "import flask, requests, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo 필요한 패키지를 설치합니다. 처음 한 번만 하며 1~2분 걸릴 수 있습니다...
  python -m pip install -r requirements.txt
  python -c "import flask, requests, openpyxl" >nul 2>&1
  if errorlevel 1 (
    echo.
    echo [오류] 필요한 패키지를 설치하지 못했습니다. 위에 나온 오류 메시지를 캡처해서 담당자에게 전달해 주세요.
    echo        - 인터넷^(사내망^) 연결과 프록시/보안 프로그램에 막히지 않았는지 확인하세요.
    echo        - 직접 설치해 보려면 이 폴더에서 아래 명령을 실행하세요:
    echo            python -m pip install -r requirements.txt
    pause
    exit /b 1
  )
)

set TF_ACL_PORT=8080
python app.py
if errorlevel 1 (
  echo.
  echo [오류] 도구가 종료되었습니다. 위의 오류 메시지를 확인하세요.
  pause
)
