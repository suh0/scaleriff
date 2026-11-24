"""연주화면 가이드 이미지(assets/guide_riff_dialog.png, guide_riff_play.png)를 더미 곡으로 찍는다.
화면 모양이 바뀌면 다시 실행. 직접 찍은 캡쳐로 같은 이름 파일을 바꿔 넣어도 된다."""
import os
from pathlib import Path
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPoint, QRect, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QApplication

from analyze.theory import song_scale_options
from gui import theme as T
from gui.main_screen import MainScreen
from gui.riff_dialog import RiffDialog
from player.dummy_timeline import build_dummy_timeline


def main():
    app = QApplication.instance() or QApplication([])
    T.load_fonts()
    tl = build_dummy_timeline()
    tl.practice["scale"] = dict(song_scale_options(tl.key_root, "major")[0])
    screen = MainScreen()
    screen.note_player.set_volume(0)
    screen.set_timeline(tl)
    screen.resize(1280, 800)
    screen.show()

    # 1) 리프 생성 창 — 목록·다시 만들기를 테두리로 강조
    dialog = RiffDialog(tl, screen._ml_model, screen)
    dialog.show()
    app.processEvents()
    pix = dialog.grab()
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(T.BORDER_ACTIVE), 3))
    for w in (dialog.list, dialog.regen_btn):
        p.drawRoundedRect(QRectF(QRect(w.mapTo(dialog, QPoint()), w.size()).adjusted(-4, -4, 4, 4)), 8, 8)
    p.end()
    pix.save(str(ROOT / "assets" / "guide_riff_dialog.png"))
    dialog.accept()                                  # 리프를 곡에 기록

    # 2) 리프모드 — 회색·초록·파랑 노드가 모두 보이는 '내 차례' 위치
    screen._select_practice("riff")
    riff = screen.riff
    roles = {T.BADGE_SCALE, T.BADGE_CHORD, T.BADGE_ROOT}
    score = {t: len(roles & {c for when, _, c, _ in riff._events
                             if t <= when <= t + riff._lead and not riff.in_call(when)})
             for t in (i / 10 for i in range(int(tl.total_sec() * 10)))}
    best = [t for t, n in score.items() if n == max(score.values())]
    screen._seek_to(best[len(best) // 2])           # 세 색이 다 보이는 구간의 가운데(가장자리에 걸치지 않게)
    curtain = getattr(screen, "_curtain", None)
    if curtain is not None:
        curtain.anim.setCurrentTime(curtain.anim.totalDuration())
    app.processEvents()
    screen.stage.grab(QRect(180, 170, 920, 560)).save(   # 레일·건반 가운데만(가이드 카드에서 노드가 크게 보이게)
str(ROOT / "assets" / "guide_riff_play.png"))
    print("GUIDE SHOTS OK")


if __name__ == "__main__":
    main()
