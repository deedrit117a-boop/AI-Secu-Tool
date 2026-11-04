@echo off
cd /d "%~dp0"
echo 배포용 zip 을 만듭니다. 환경 목록도 넣으려면: make_dist.bat --with-config
python make_dist.py %*
pause
