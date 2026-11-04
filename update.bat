@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ==============================================================
echo  Traform ACL Tool 업데이트 - 이전 버전의 설정을 이 폴더로 옮깁니다
echo ==============================================================
echo.
echo  새 zip 을 푼 폴더(지금 이 폴더)에서 실행하는 도구입니다.
echo  토큰, 환경 목록, 메타 데이터, 작업 이력이 들어 있는 이전 폴더의 data 를 복사합니다.
echo  이전 폴더는 지우지 않습니다. 문제가 없으면 나중에 직접 지우세요.
echo.

if not exist "app.py" (
  echo [오류] 새 버전 폴더에서 실행해 주세요. app.py 가 이 폴더에 없습니다.
  pause
  exit /b 1
)
if exist "data\local.json" (
  echo [안내] 이 폴더에는 이미 data\local.json 이 있습니다. 덮어쓰면 현재 설정이 사라집니다.
  set /p OVR=그래도 이전 폴더의 data 로 덮어쓸까요? (y/N): 
  if /i not "!OVR!"=="y" (
    echo 취소했습니다.
    pause
    exit /b 0
  )
)

echo 이전 버전 폴더의 경로를 입력하세요. 폴더를 이 창으로 끌어다 놓아도 됩니다.
set "OLD="
set /p OLD=이전 폴더: 
set "OLD=!OLD:"=!"
if "!OLD!"=="" (
  echo 경로가 비어 있어 취소했습니다.
  pause
  exit /b 1
)
for %%I in ("!OLD!") do set "OLD=%%~fI"
for %%I in ("%~dp0.") do set "NEW=%%~fI"

if /i "!OLD!"=="!NEW!" (
  echo [오류] 이전 폴더와 새 폴더가 같습니다. 서로 다른 폴더여야 합니다.
  pause
  exit /b 1
)
if not exist "!OLD!\data\" (
  echo [오류] 이전 폴더에 data 폴더가 없습니다: !OLD!
  echo        이전에 쓰던 Traform ACL Tool 폴더인지 확인하세요.
  pause
  exit /b 1
)

netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo.
  echo [주의] 8080 포트에서 서버가 실행 중입니다. 이전 도구의 서버 콘솔 창을 닫은 뒤 진행하세요.
  echo        실행 중에 복사하면 작업 이력이 최신이 아닐 수 있습니다.
  set /p GO=그래도 계속할까요? (y/N): 
  if /i not "!GO!"=="y" (
    echo 취소했습니다.
    pause
    exit /b 0
  )
)

echo.
echo 복사 중: !OLD!\data  ->  !NEW!\data
robocopy "!OLD!\data" "!NEW!\data" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 (
  echo [오류] data 를 복사하지 못했습니다. 파일이 사용 중이거나 권한이 없을 수 있습니다.
  pause
  exit /b 1
)
echo  data 복사 완료.

if exist "!OLD!\repos\" (
  if not exist "repos\" (
    echo.
    echo 이전 폴더에 내려받은 저장소(repos)가 있습니다. 옮기면 다시 내려받지 않아도 됩니다.
    set /p MV=repos 폴더를 이 폴더로 옮길까요? (Y/n): 
    if /i not "!MV!"=="n" (
      move "!OLD!\repos" "!NEW!\repos" >nul
      if errorlevel 1 (
        echo [안내] 옮기지 못했습니다. 작업 탭에서 저장소를 다시 내려받으면 됩니다.
      ) else (
        echo  repos 이동 완료.
      )
    )
  )
)

echo.
echo 업데이트 준비가 끝났습니다. run.bat 으로 시작하세요.
echo 화면의 환경설정 - 자가 점검에서 '점검 실행'을 눌러 이상이 없는지 확인할 수 있습니다.
echo.
set /p RUN=지금 run.bat 을 실행할까요? (Y/n): 
if /i not "!RUN!"=="n" call "%~dp0run.bat"
endlocal
