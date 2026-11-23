"""즉흥연주 트레이너 — 진입점.

실행:  .venv/Scripts/python.exe main.py
"""
import sys
import os

# 패키지 임포트를 위해 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Qt 6.11에서 실제 seek/속도/반복 검증한 백엔드. 레거시 Windows WMF는
# 로딩 중 seek를0초로 되돌릴 수 있다. QtMultimedia import 전에 설정한다.
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication
from gui.app import AppWindow


class _NoToolTips(QObject):
    """마우스 호버 툴팁을 앱 전체에서 끈다."""
    def eventFilter(self, obj, event):
        return event.type() == QEvent.Type.ToolTip


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("즉흥연주 트레이너")
    app._no_tips = _NoToolTips(app)
    app.installEventFilter(app._no_tips)
    win = AppWindow()
    win.showFullScreen()   # 작업표시줄·제목표시줄 없는 전체화면(상단 호버 시 창 버튼)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
