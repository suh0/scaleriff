"""다음 스케일 예고의 타이밍과 실제 건반 채색 검사."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage, QPainter, QColor
from PyQt6.QtCore import QRectF
from gui.main_screen import MainScreen
from gui import theme as T
from player.dummy_timeline import build_dummy_timeline


def main():
    app = QApplication([])
    screen = MainScreen()
    tl = build_dummy_timeline()
    screen.set_timeline(tl)
    piano = screen.piano
    boundary = tl.segments[1].start_sec
    lead = 2 * tl.beat_sec()
    screen._render_at(boundary - lead)
    assert piano._preview_opacity == 0
    screen._render_at(boundary - lead * 0.8)
    assert abs(piano._preview_opacity - 0.488) < 1e-6
    screen._render_at(boundary - lead / 2)
    assert abs(piano._preview_opacity - 0.875) < 1e-6
    assert piano._degrees[2] == "1", "경계 전 현재 D 도리안 배지 유지"
    assert piano._preview_root == 7, "다음 G 믹솔리디안 예고"
    before = piano._preview_opacity
    app.processEvents()
    assert piano._preview_opacity == before, "재생 위치 없이는 진행하지 않음"

    def pixel(midi, black=False, x=30):
        img = QImage(60, 160, QImage.Format.Format_ARGB32)
        img.fill(QColor("transparent"))
        painter = QPainter(img)
        draw = piano._draw_black if black else piano._draw_white
        draw(painter, midi, QRectF(0, 0, 60, 160))
        painter.end()
        return img.pixelColor(x, 30)

    faint = pixel(67, x=1)
    screen._render_at(boundary - 0.001)
    assert 0.99 < piano._preview_opacity <= 1.0
    strong = pixel(67, x=1)
    assert strong.red() < faint.red(), "G 건반 테두리가 점점 파랗게 물듦"
    assert pixel(67) == QColor(T.KEY_W_FILL), "흰 건반 내부 색 유지"
    piano.set_preview([7], [7], 7, 1)
    assert piano._preview_opacity == 1.0
    assert pixel(67, x=1) == QColor(T.BADGE_ROOT), "최대 진하기는 원래 색 100%"
    piano.set_preview([7, 9, 11], [7, 11], 7, 1)
    assert pixel(71, x=1) == QColor(T.BADGE_CHORD), "초록 코드톤 예고 유지"
    assert pixel(69, x=1) == QColor(T.KEY_W_FILL), "회색 스케일음은 예고하지 않음"
    assert pixel(61, True) == QColor(T.KEY_B_FILL), "다음 스케일 밖 건반 유지"
    piano.set_preview([1], [], 1, 1)
    assert pixel(61, True, x=1) == QColor(T.BADGE_ROOT), "검은 건반 테두리 채색"
    assert pixel(61, True) == QColor(T.KEY_B_FILL), "검은 건반 내부 색 유지"
    piano.set_pressed({61})
    assert pixel(61, True) == QColor(T.KEY_PRESSED_OUT), "눌림 색 우선"
    assert pixel(61, True, x=1) == QColor(T.KEY_PRESSED_OUT), "눌림 시 예고 테두리 숨김"
    piano.set_pressed(set())
    screen._render_at(boundary)
    assert piano._preview_opacity == 0
    assert piano._degrees[7] == "1", "경계에서 새 스케일 배지 전환"
    screen._render_at(tl.total_sec())
    assert piano._preview_opacity == 0, "마지막 구간 후 예고 없음"
    screen._render_at(0)
    assert piano._preview_opacity == 0, "되감기 시 예고 초기화"
    print("SCALE PREVIEW OK")


if __name__ == "__main__":
    main()
