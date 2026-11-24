"""연주 무대 실제 창 측정: CPU 무대와 GL 무대(gui/widgets/gl_stage)를 같은 조건으로 재생하며 프레임을 잰다.
소리 없이 재생하고 창을 최대화로 띄웠다 닫는다(실제 화면 합성·DPI 배율 그대로 — 오프스크린 측정과 다름).

사용: .venv\\Scripts\\python.exe tools\\stage_bench.py <세션.json> cpu|gl [초=15] [held] [riff]
  held = 재생 중 건반 2개(E4·G4)를 계속 누른 상태 · riff = 리프모드(리프 생성 창에서 확정한 상태)
  mute = 프로그램 차례 리프 음 재생 끔(소리 재생이 프레임에 주는 영향 가르기)
출력: 무대 그리기 CPU 시간, 프레임 간격(gl은 화면 교체 간격), 25ms 넘는 프레임 수, 30초 위치 실제 화면 캡처 PNG(임시 폴더).
"""
import os
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

path, mode = sys.argv[1], sys.argv[2]
secs = float(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].replace(".", "").isdigit() else 15.0
held, riff = "held" in sys.argv, "riff" in sys.argv
if mode == "cpu":
    os.environ["SCALERIFF_STAGE"] = "cpu"

from PyQt6.QtCore import QTimer                     # noqa: E402
from PyQt6.QtWidgets import QApplication            # noqa: E402

app = QApplication(sys.argv)
from gui.app import AppWindow                       # noqa: E402
from gui.widgets.stage import Stage                 # noqa: E402
from player.timeline import Timeline                # noqa: E402

frames = []                                         # (그리기 시작, 끝) — gl은 화면 교체 시각 기준
_paint = Stage.paintEvent


def paint(self, e):
    t0 = time.perf_counter()
    _paint(self, e)
    if self.gl is None:
        frames.append((t0, time.perf_counter()))


Stage.paintEvent = paint
win = AppWindow()
tl = Timeline.load_json(path)
tl.audio_ref = ""
win._timeline = tl
win.showMaximized()
app.processEvents()
ms = win.main_screen
ms.set_timeline(tl)
win.stack.setCurrentWidget(ms)
if riff:
    from gui.riff_dialog import RiffDialog          # noqa: E402
    RiffDialog(ms.tl, ms._ml_model, ms).accept()
    ms._select_practice("riff")
if "mute" in sys.argv:                              # 리프 음 재생(QSoundEffect, GUI 스레드) 끔 — 소리 영향 가르기
    ms.note_player.play_note = lambda *a, **k: None
if mode == "gl" and ms.gl_stage is None:
    raise SystemExit("GL 무대를 쓸 수 없는 환경(SCALERIFF_STAGE=cpu 또는 OpenGL 2.1 없음)")
swaps = []
if ms.gl_stage is not None:
    ms.gl_stage.frameSwapped.connect(lambda: swaps.append(time.perf_counter()))


def start():                                        # 화면 전환·커튼이 끝난 뒤
    frames.clear()
    swaps.clear()
    ms.playhead.play()
    if held:
        QTimer.singleShot(200, lambda: [ms.on_midi_note(m, True) for m in (64, 67)])
    QTimer.singleShot(int(secs * 1000), finish)


def finish():
    ms.playhead.pause()
    q = lambda d, k: sorted(d)[int(k * (len(d) - 1))]   # noqa: E731
    if ms.gl_stage is not None:
        draw = ms.gl_stage.frame_ms[-len(swaps):]
        times = swaps
    else:
        draw = [(b - a) * 1000 for a, b in frames]
        times = [a for a, _ in frames]
    gaps = [(b - a) * 1000 for a, b in zip(times, times[1:])]
    size = f"{ms.stage.width()}x{ms.stage.height()} @{ms.stage.devicePixelRatioF():g}"
    print(f"[{mode}{' held' if held else ''}{' riff' if riff else ''}] 무대 {size}  {len(gaps) / secs:.1f}fps")
    print(f"  그리기 CPU  med {q(draw, .5):5.1f}  p95 {q(draw, .95):5.1f}  max {max(draw):5.1f} ms")
    print(f"  프레임 간격 med {q(gaps, .5):5.1f}  p95 {q(gaps, .95):5.1f}  max {max(gaps):5.1f} ms"
          f"  >25ms {sum(g > 25 for g in gaps)}회")
    ms._seek_to(30.0)
    if held:
        for m in (64, 67):
            ms.on_midi_note(m, True)
    QTimer.singleShot(400, capture)


def capture():
    name = f"stage_{mode}{'_held' if held else ''}{'_riff' if riff else ''}.png"
    out = pathlib.Path(tempfile.gettempdir()) / name
    g = win.frameGeometry()
    app.primaryScreen().grabWindow(0, g.x(), g.y(), g.width(), g.height()).save(str(out))
    print(f"  캡처 {out}")
    app.quit()


QTimer.singleShot(3000, start)
app.exec()
