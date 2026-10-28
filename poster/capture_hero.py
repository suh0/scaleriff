"""포스터 대표 이미지: 리프모드 낙하 노드 장면을 offscreen 3배율로 캡처.

실행(저장소 루트): PYTHONUTF8=1 .venv/Scripts/python.exe poster/capture_hero.py
결과: poster/hero_full.png(창 전체 4800×2700)
"""
import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "3"   # 1600×900 논리 px → 4800×2700
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt6.QtWidgets import QApplication, QDialog
from player.timeline import Timeline
from gui import theme as T
from gui.main_screen import MainScreen
from gui.riff_dialog import RiffDialog
from gui.widgets import stage as stage_mod
from gui.widgets.piano import MIDI_HIGH, MIDI_LOW

SESSION = "cache/KIRINJI 키린지 - Drifter 드리프터_a96f1ed47fc18957.json"
OUT = os.path.join(ROOT, "poster")


def main():
    app = QApplication([])
    T.load_fonts()
    app.setStyleSheet(T.qss_app())
    screen = MainScreen()
    screen.resize(1600, 900)
    screen.show()
    screen.set_timeline(Timeline.load_json(SESSION))
    app.processEvents()

    dialog = RiffDialog(screen.tl, screen._ml_model, screen)
    dialog.make_riffs()
    dialog.done(QDialog.DialogCode.Accepted)
    screen._select_practice("riff")

    # 노드가 가장 촘촘한 시점: 화면에 보이는 구간(4박) 안 두 옥타브 노드 수 최대
    lead = screen.riff._lead
    times = [w for w, m, *_ in screen.riff._events if MIDI_LOW <= m <= MIDI_HIGH]
    t = max(times, key=lambda w: sum(w <= x < w + lead for x in times))
    screen._seek_to(t - 0.02)
    app.processEvents()

    # 타격 효과: t에 도착하는 노드를 누르고 판정 스플래시
    midi = next(m for w, m, *_ in screen.riff._events if w == t and MIDI_LOW <= m <= MIDI_HIGH)
    screen.piano.set_pressed({midi})
    hit = screen.riff.judge(midi, t)
    assert hit, "판정 창 안의 노드여야 함"
    screen.stage.splash(*hit)
    c, r, _, label = screen.stage._splashes[-1]   # 링이 퍼지기 시작한 순간으로
    screen.stage._splashes[-1] = (c, r, time.monotonic() - 0.2 * stage_mod.SPLASH_LIFE, label)
    screen.play_btn.hide()
    screen.stage.update()
    app.processEvents()

    img = screen.grab()
    img.save(os.path.join(OUT, "hero_full.png"))
    print(f"t={t:.2f}s midi={midi} hit={hit[0]} size={img.width()}x{img.height()}")


if __name__ == "__main__":
    main()
