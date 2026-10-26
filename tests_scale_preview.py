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
    assert piano._chord_root == 2, "경계 직전엔 현재 Dm7 근음 그대로(다음 코드 미리 안 보임)"
    screen._render_at(boundary)
    assert piano._chord_root == 7, "경계에서 G7 근음으로 전환"
    assert piano._degrees[0] == "1" and piano._degrees[7] == "5", "번호는 곡 주음(C) 기준 고정"
    print("SCALE PREVIEW OK")


if __name__ == "__main__":
    main()
