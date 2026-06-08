"""즉흥연주 트레이너 — 진입점.

실행:  venv\Scripts\python.exe main.py
"""
import sys
import os

# 패키지 임포트를 위해 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from gui.app import AppWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("즉흥연주 트레이너")
    win = AppWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
