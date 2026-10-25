"""리프 음표의 낙하·건반 정렬·구간 이동·루프 예고 검사."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication
from gui.main_screen import MainScreen
from player.dummy_timeline import build_dummy_timeline


def main():
    app = QApplication([])
    screen = MainScreen()
    tl = build_dummy_timeline()
    screen.set_timeline(tl)
    for seg in tl.segments:
        seg.example = []
    tl.segments[0].example = [
        {"midi": 62, "beat_pos": 2, "dur_beats": 0.5},
        {"midi": 66, "beat_pos": 3, "dur_beats": 1.0},
    ]
    screen.resize(1040, 740)
    screen.show()
    app.processEvents()
    screen._mode_actions["riff"].trigger()
    assert screen.piano._preview_opacity == 0, "정지 중 모드 선택도 스케일 예고 제거"
    screen._on_seek(0)
    before = screen.riff._nodes()
    assert len(before) == 2
    assert abs(before[1][3] - before[0][3] * 2) < 1e-6, "1박 막대는 반 박 막대의 두 배 길이"
    screen._on_seek(0.6)
    after = screen.riff._nodes()
    assert all(b[1] > a[1] for a, b in zip(before, after)), "박자 진행에 따라 아래로 낙하"
    app.processEvents()
    assert screen.riff._nodes() == after, "일시정지 중 노드 정지"
    screen.piano.set_pressed({62, 66})
    assert screen.riff._nodes() == after, "눌린 건반도 리프 예고 유지"
    screen._on_seek(1.2)
    node = screen.riff._nodes()[0]
    assert abs(node[1] + node[3] - screen.riff.height()) < 1e-6, "해당 박자에 막대 아래 끝 도착"
    bottom = screen.riff.mapTo(screen.content, QPoint(0, screen.riff.height())).y()
    assert abs(bottom - (screen.piano.y() + screen.piano._geometry()[2])) <= 1
    for x, _, _, _, _ in screen.riff._nodes():
        assert screen.piano._midi_at(x, screen.piano._geometry()[2] + 1) in (62, 66), \
            "흰 건반·흑건의 실제 위치와 노드 정렬"
    screen._on_seek(1.21)
    assert len(screen.riff._nodes()) == 2, "음표 길이 동안 막대 유지"
    assert screen.riff._nodes()[0][1] > node[1], "음표 길이에 맞춰 건반 안으로 내려감"
    screen._on_seek(1.5)
    assert len(screen.riff._nodes()) == 1, "끝난 음표는 제거"
    screen._on_seek(0)
    assert screen.riff._nodes() == before, "되감기 시 노드 초기화"
    screen._on_seek(2.3)
    assert len(screen.riff._nodes()) == 1, "긴 음표는 종료까지 유지"
    screen._on_seek(2.41)
    assert not screen.riff._nodes()
    tl.loops = [{"name": "loop", "start_bar": 0, "end_bar": 0, "on": True}]
    screen._render_at(2.3)
    assert len(screen.riff._nodes()) == 3, "지속 중인 음과 루프 다음 회차 리프 예고"
    screen._select_practice("riff")
    screen._render_at(1.0)
    assert screen.riff.isVisible() and screen.piano._preview_opacity == 0
    tl.loops = []
    screen._select_practice("free")
    screen._render_at(1.0)
    assert screen.riff.isHidden() and screen.piano._preview_opacity > 0
    screen.close()
    print("FALLING NOTES OK")


if __name__ == "__main__":
    main()
