"""포스터 프로세스·건반 이미지: 링크 입력·분석 중·박자 보정·자유연습 건반 화면을 offscreen 3배율로 캡처.

실행(저장소 루트): PYTHONUTF8=1 .venv/Scripts/python.exe poster/capture_screens.py
결과: poster/shot_link.png, shot_analyzing.png, shot_beat.png, shot_keys.png (각 3840×2400)
"""
import glob
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "3"   # 1280×800 논리 px → 3840×2400
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from player.timeline import Timeline
from gui.app import AppWindow

SESSION = "cache/KIRINJI 키린지 - Drifter 드리프터_a96f1ed47fc18957.json"
OUT = os.path.join(ROOT, "poster")


def shot(win, page, name):
    win.stack.setCurrentWidget(page)
    QTest.qWait(1500)                  # 등장 애니메이션(stagger) 끝까지
    img = win.centralWidget().grab()
    img.save(os.path.join(OUT, name))
    print(name, f"{img.width()}x{img.height()}")


def main():
    app = QApplication([])
    win = AppWindow()
    win.resize(1280, 800)
    win.show()

    win.link_screen.stack.setCurrentWidget(win.link_screen._input)
    win.link_screen.set_recent(sorted(glob.glob(os.path.join(ROOT, "cache", "*_*.json")))[:4])
    shot(win, win.link_screen, "shot_link.png")

    win.analyzing._on_progress(62, "코드 인식(madmom 학습 모델)… 잠시 걸려요")
    shot(win, win.analyzing, "shot_analyzing.png")

    tl = Timeline.load_json(SESSION)
    win.beat.set_timeline(tl)
    shot(win, win.beat, "shot_beat.png")

    win.main_screen.set_timeline(tl)
    win.main_screen._seek_to(tl.segments[len(tl.segments) // 3].start_sec + 0.1)
    win.main_screen.play_btn.hide()
    shot(win, win.main_screen, "shot_keys.png")
    win.main_screen.pause()


if __name__ == "__main__":
    main()
