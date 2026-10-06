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
    lead = 4 * tl.beat_sec()
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

    def render_key(midi, black=False):
        img = QImage(60, 188, QImage.Format.Format_ARGB32)
        img.fill(QColor("transparent"))
        painter = QPainter(img)
        draw = piano._draw_black if black else piano._draw_white
        draw(painter, midi, QRectF(0, 12, 60, 160))
        piano._draw_preview_bar(painter, midi, QRectF(0, 12, 60, 160))
        painter.end()
        return img

    def pixel(midi, black=False, x=30, y=42):
        return render_key(midi, black).pixelColor(x, y)

    faint = pixel(67, y=178)
    assert faint.alpha() > 0, "건반 아래에 예고 막대 표시"
    screen._render_at(boundary - 0.001)
    assert 0.99 < piano._preview_opacity <= 1.0
    strong = pixel(67, y=178)
    assert strong.alpha() > faint.alpha(), "G 건반 아래 막대가 점점 선명해짐"
    assert pixel(67) == QColor(T.KEY_W_FILL), "흰 건반 내부 색 유지"
    piano.set_preview([7], [7], 7, 1)
    assert piano._preview_opacity == 1.0
    assert pixel(67, y=178) == QColor(T.BADGE_ROOT), "최대 진하기는 원래 색 100%"
    assert pixel(67, y=6).alpha() == 0, "건반 위 예고 제거"
    assert pixel(67, x=1) == QColor(T.KEY_W_FILL), "예고 테두리는 제거"
    widths = []
    for progress in (0, 0.2, 0.5, 1):
        piano.set_preview([7], [7], 7, progress)
        img = render_key(67)
        widths.append(sum(img.pixelColor(x, 178).alpha() > 0 for x in range(60)))
    assert widths[0] == 0 and widths[0] < widths[1] < widths[2] < widths[3], widths
    assert widths[3] == 60, "최대 막대 너비는 건반 너비"
    piano.set_preview([7, 9, 11], [7, 11], 7, 1)
    assert pixel(71, y=178) == QColor(T.BADGE_CHORD), "초록 코드톤 예고 유지"
    assert pixel(69, y=178).alpha() == 0, "회색 스케일음은 예고하지 않음"
    assert pixel(61, True) == QColor(T.KEY_B_FILL), "다음 스케일 밖 건반 유지"
    piano.set_preview([1], [], 1, 1)
    assert pixel(61, True, y=170) == QColor(T.BADGE_ROOT), "흑건 맨 아래에 막대 표시"
    assert pixel(61, True, y=178).alpha() == 0, "흑건 예고는 흰 건반 아래에 표시하지 않음"
    assert pixel(61, True) == QColor(T.KEY_B_FILL), "검은 건반 내부 색 유지"
    piano.set_pressed({61})
    assert pixel(61, True) == QColor(T.KEY_PRESSED_OUT), "눌림 색 우선"
    assert pixel(61, True, y=170) == QColor(T.BADGE_ROOT), "눌린 흑건에도 예고 막대 유지"
    piano.set_scale([1, 2], [1, 2])
    piano.set_degrees({1: "1", 2: "1"})
    for midi, black, badge_y in ((62, False, 144), (61, True, 147)):
        piano.set_pressed(set())
        badge_color = pixel(midi, black, y=badge_y)
        assert badge_color == QColor(T.BADGE_ROOT), "숫자구 색 확인"
        piano.set_pressed({midi})
        assert pixel(midi, black) == QColor(T.BADGE_ROOT), "1번 건반 눌림은 파랑"
        assert pixel(midi, black, y=badge_y) == badge_color, "눌러도 숫자구 유지"
        badge_image = render_key(midi, black)
        assert all(badge_image.pixelColor(x, y) == badge_color
                   for x in range(26, 34) for y in range(badge_y + 5, badge_y + 9)), \
            "색 구 중앙에 숫자가 남아 있음"
    assert pixel(61, True, y=170) == QColor(T.BADGE_ROOT), "숫자구와 예고 막대 동시 표시"
    piano.set_degrees({1: "3", 2: "3"})
    for midi, black in ((62, False), (61, True)):
        piano.set_pressed({midi})
        assert pixel(midi, black) == QColor(T.KEY_PRESSED_CHORD), "다른 코드톤은 초록 유지"
    piano.set_pressed(set())
    screen._render_at(boundary)
    assert piano._preview_opacity == 0
    assert pixel(67, y=178).alpha() == 0, "전환 순간 예고 막대 제거"
    assert piano._degrees[7] == "1", "경계에서 새 스케일 배지 전환"
    screen._render_at(tl.total_sec())
    assert piano._preview_opacity == 0, "마지막 구간 후 예고 없음"
    screen._render_at(0)
    assert piano._preview_opacity == 0, "되감기 시 예고 초기화"
    print("SCALE PREVIEW OK")


if __name__ == "__main__":
    main()
