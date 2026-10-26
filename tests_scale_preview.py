"""자유연습: 다음 스케일 예고 없음 — 건반 상태는 코드 경계에서 바로 바뀐다."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from gui.main_screen import MainScreen
from player.dummy_timeline import build_dummy_timeline


def main():
    app = QApplication([])
    screen = MainScreen()
    tl = build_dummy_timeline()
    screen.set_timeline(tl)
    piano = screen.piano
    boundary = tl.segments[1].start_sec
    assert not hasattr(piano, "set_preview") and not hasattr(screen.stage, "_draw_preview"), "예고 기능 제거"
    screen._render_at(boundary - 0.001)
    assert piano._degrees[2] == "1", "경계 직전엔 현재 D 도리안 그대로(다음 스케일 미리 안 보임)"
    screen._render_at(boundary)
    assert piano._degrees[7] == "1", "경계에서 새 스케일로 전환"
    print("SCALE PREVIEW OK")


if __name__ == "__main__":
    main()
