"""화면 자동 테스트용 가짜 서버. 내용은 프로젝트 루트의 demo_server.py(시연 모드와 같은 가짜 데이터 서버)를 그대로 실행한다.

실행:  python tests/ui_server.py [포트]     (tests/ui/run_ui_tests.js 가 자동으로 실행/종료)
"""
import os
import runpy
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
runpy.run_path(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo_server.py"), run_name="__main__")
