"""즉흥연주 트레이너 — 진입점.

실행:  venv\Scripts\python.exe main.py
"""
import sys
import os

# 패키지 임포트를 위해 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Qt6 기본 FFmpeg 오디오 백엔드가 장시간/반복 재생 후 전체 무음에 빠지는
# 문제 회피 — Windows 네이티브(WASAPI 레거시) 백엔드 사용. QtMultimedia
# 임포트 전에 설정해야 적용된다.
os.environ.setdefault("QT_MEDIA_BACKEND", "windows")

from PyQt6.QtWidgets import QApplication
from gui.app import AppWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("즉흥연주 트레이너")
    win = AppWindow()
    win.showMaximized()   # 시작 시 전체화면(최대화)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
