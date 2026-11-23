"""GPU 시험판: 실제 창에서 연주 무대 프레임을 세 방식으로 비교한다. 소리 없이 재생하며 창을 최대화로 띄웠다 닫는다.
  cpu    = 지금 무대(QWidget 래스터)
  gl     = 무대 코드 그대로, 바탕만 QOpenGLWidget(QPainter OpenGL 엔진)
  shader = 움직이는 부분(박자·코드선, 점선, 코드 색 띠 직육면체, 박 펄스)을 셰이더로 직접, 배경·건반 층은
           지금 구운 그림을 텍스처로. 자유연습 범위만(리프 노드·번짐·별빛·눌린 건반·빛기둥·아지랑이 없음)

사용: .venv\\Scripts\\python.exe tools\\gl_trial.py <세션.json> cpu|gl|shader [초=20] [held]
  held = 재생 중 건반 2개(E4·G4)를 계속 누른 상태
출력: 무대 그리기 CPU 시간, 프레임 간격(체감 끊김), gl·shader는 화면 교체(frameSwapped) 간격, 같은 시각 무대 캡처 PNG.
"""
import pathlib
import statistics
import sys
import tempfile
import time
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QSurfaceFormat
from PyQt6.QtWidgets import QApplication

path, mode = sys.argv[1], sys.argv[2]
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0
held = "held" in sys.argv[4:]
tag = " ".join(a for a in sys.argv[4:] if a != "held")

if mode in ("gl", "shader", "native"):
    fmt = QSurfaceFormat()
    fmt.setSamples(0 if "nomsaa" in sys.argv else 4)   # 안티앨리어싱(래스터의 AA 대신 멀티샘플)
    fmt.setSwapInterval(0 if "novsync" in sys.argv else 1)
    QSurfaceFormat.setDefaultFormat(fmt)
app = QApplication(sys.argv)

if mode == "gl":                # stage.py 원본을 그대로, 바탕 클래스만 바꿔 불러온다(제품 코드 무변경)
    src = (ROOT / "gui/widgets/stage.py").read_text(encoding="utf-8")
    assert "class Stage(QWidget):" in src
    mod = types.ModuleType("gui.widgets.stage")
    mod.__file__ = str(ROOT / "gui/widgets/stage.py")
    code = "from PyQt6.QtOpenGLWidgets import QOpenGLWidget\n" + src.replace("class Stage(QWidget):",
                                                                         "class Stage(QOpenGLWidget):")
    exec(compile(code, mod.__file__, "exec"), mod.__dict__)
    sys.modules["gui.widgets.stage"] = mod

from gui.app import AppWindow                       # noqa: E402 — 위 교체 뒤에 불러와야 함
from gui.widgets.stage import Stage                 # noqa: E402
from player.timeline import Timeline                # noqa: E402

paints, swaps = [], []
_paint = Stage.paintEvent


def paint(self, e):
    if mode in ("shader", "native"):                # 무대는 모델(기하·캐시)로만 — 그리기는 셰이더 층이
        self.gl_layer.update()
        return
    t0 = time.perf_counter()
    _paint(self, e)
    paints.append((t0, time.perf_counter()))


Stage.paintEvent = paint

win = AppWindow()
tl = Timeline.load_json(path)
tl.audio_ref = ""                                   # 소리 없이(그리기만 비교)
win._timeline = tl
ms = win.main_screen
stage = ms.stage
if mode in ("shader", "native"):
    import shader_stage                             # noqa: E402
    stage.gl_layer = (shader_stage.ShaderLayer if mode == "shader" else shader_stage.NativeLayer)(stage, paints)
    # 무대(래스터)를 다시 그리라 하면 화면 대부분이 매 프레임 창 합성 텍스처로 다시 올라감 → 셰이더 층만
    stage.update = lambda *a: stage.gl_layer.update()
win.showMaximized()
app.processEvents()
ms.set_timeline(tl)
win.stack.setCurrentWidget(ms)
gl_widget = {"gl": stage, "shader": getattr(stage, "gl_layer", None), "native": getattr(stage, "gl_layer", None)}.get(mode)
if gl_widget is not None:
    gl_widget.frameSwapped.connect(lambda: swaps.append(time.perf_counter()))
ticks = []                                          # 재생 틱 처리(코드 표시·재생바·건반 상태 등 파이썬)
_tick = ms._on_tick


def tick(sec):
    t0 = time.perf_counter()
    _tick(sec)
    ticks.append((time.perf_counter() - t0) * 1000)


ms.playhead.positionChanged.disconnect(ms._on_tick)
ms._on_tick = tick
ms.playhead.positionChanged.connect(tick)


if "nohud" in sys.argv:                             # 합성 비용 가르기: 재생 중 HUD(재생바·시간·코드 표시) 갱신 끔
    ms.scrub.set_position = lambda *a: None
    ms._set_time = lambda *a: None
    ms.chord_hdr.set_chords = lambda *a: None


def start():                                        # 전환·커튼이 끝난 뒤 재생
    paints.clear()
    swaps.clear()
    ticks.clear()
    ms.playhead.play()
    if held:
        QTimer.singleShot(200, lambda: [ms.on_midi_note(m, True) for m in (64, 67)])
    QTimer.singleShot(int(secs * 1000), finish)


def finish():
    ms.playhead.pause()
    q = lambda d, k: sorted(d)[int(k * (len(d) - 1))]   # noqa: E731
    draw = [(b - a) * 1000 for a, b in paints]
    gaps = [(b[0] - a[0]) * 1000 for a, b in zip(paints, paints[1:])]
    size = f"{stage.width()}x{stage.height()} @{stage.devicePixelRatioF():g}"
    print(f"[{mode}{' held' if held else ''} {tag}] 무대 {size}  frames {len(paints)} ({len(paints) / secs:.1f}fps)")
    print(f"  paint CPU  med {q(draw, .5):5.1f}  p95 {q(draw, .95):5.1f}  max {max(draw):5.1f} ms")
    print(f"  프레임 간격 med {q(gaps, .5):5.1f}  p95 {q(gaps, .95):5.1f}  max {max(gaps):5.1f} ms"
          f"  >25ms {sum(g > 25 for g in gaps)}회")
    if swaps:
        sw = [(b - a) * 1000 for a, b in zip(swaps, swaps[1:])]
        print(f"  화면 교체  med {q(sw, .5):5.1f}  p95 {q(sw, .95):5.1f}  max {max(sw):5.1f} ms"
              f"  >25ms {sum(g > 25 for g in sw)}회")
        after = [min((s - b for s in swaps if s > b), default=0) * 1000 for _, b in paints[:-1]]
        print(f"  그리기 끝→화면 교체(창 합성) med {q(after, .5):5.1f}  p95 {q(after, .95):5.1f} ms")
    print(f"  재생 틱 처리 med {q(ticks, .5):5.1f}  p95 {q(ticks, .95):5.1f}  max {max(ticks):5.1f} ms  ({len(ticks)}회)")
    ms._seek_to(30.0)                               # 같은 시각 캡처(눈으로 비교)
    app.processEvents()
    out = pathlib.Path(tempfile.gettempdir()) / f"gl_trial_{mode}{'_held' if held else ''}.png"
    if mode == "native":
        gl_widget.grabFramebuffer().save(str(out))
    else:
        (gl_widget if mode == "shader" else stage).grab().save(str(out))
    print(f"  캡처 {out}")
    app.quit()


QTimer.singleShot(3000, start)
app.exec()
