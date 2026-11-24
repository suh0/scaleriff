"""GL 무대 — 연주 무대(Stage)를 네이티브 OpenGL 창에서 셰이더로 그린다(실제 창 60fps용).

Stage는 그대로 모델(기하·장면·건반 캐시)이고 화면만 이 창이 덮는다(Stage.gl). 위젯 창 합성을 거치지 않아
그리기 ~5ms + vsync에 맞춰 연속으로 그린다(QOpenGLWidget은 Qt 위젯 합성이 HUD가 바뀔 때마다 ~7ms 더 듦 — 시험 실측).
네이티브 창 밑에 가려진 위젯은 Qt가 그리지 않으므로 HUD는 MainScreen이 투명 도구 창(HudWindow)으로 위에 띄우고,
계속 움직이는 코드 표시만 이 창이 대신 그린다(mirror). 측정: tools/stage_bench.py.

평면(레인) 정점은 [x, y, 높이, r, g, b, a] — 원근(Stage._xf)과 직육면체 높이(Stage._block과 같은 식)는 정점 셰이더가
계산한다. 화면 좌표로만 정해지는 것(번짐 띠·모서리 선)은 역변환으로 평면 점을 만들어 같은 셰이더로.
배경·건반 층·안개·별빛은 텍스처. 눌린 건반은 건반별 그림(상태·발광색·눌림별 한 번 CPU로)을 띠 안에 얹고,
스플래시는 살아 있는 동안 작은 그림에 CPU로 그려 올린다.
"""
from __future__ import annotations

import math
import os
import time
import traceback
from collections import OrderedDict

import numpy as np
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import (QColor, QGuiApplication, QImage, QMouseEvent, QOpenGLContext, QPainter, QPolygonF,
                         QSurfaceFormat)
from PyQt6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture, QOpenGLWindow,
                            QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile)
from PyQt6.QtWidgets import QApplication, QWidget

from gui import theme as T
from gui.anim import CAST, STRIPS as S_STRIPS, reduced_motion
from gui.widgets import stage as S

GL_FLOAT, GL_TRIANGLES, GL_LINES = 0x1406, 0x0004, 0x0001
GL_BLEND, GL_SCISSOR_TEST, GL_LINE_SMOOTH = 0x0BE2, 0x0C11, 0x0B20
GL_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA = 0x0302, 1, 0x0303
GL_COLOR_BUFFER_BIT = 0x4000
SPRITE_CACHE = 160          # 건반별 그림(상태·발광색·눌림별) 보관 개수 — 장당 ~0.3MB
HALO_RINGS = ((3.5, 0.395), (8.0, 0.135))   # 노드 번짐 = Stage._halo(16px·7px 겹)의 바깥 절반: (끝 거리 px, 불투명도)

GEO_VS = """
#version 120
attribute vec2 plane;      // 평면 좌표(레인)
attribute float height;    // 판정선 기준 화면 px 높이(Stage._block의 lift·lift+lip)
attribute vec4 color;
uniform vec3 c0, c1, c2;   // QTransform 열: 화면 = (x*c0 + y*c1 + c2).xy / z
uniform vec2 size;         // 창 논리 크기
uniform float k;           // 판정선 깊이에서 평면 1px의 화면 폭
varying vec4 v_color;
void main() {
    vec3 p = plane.x * c0 + plane.y * c1 + c2;
    vec2 s = p.xy / p.z;
    float unit = (c0.x * p.z - p.x * c0.z) / (p.z * p.z);   // 이 깊이에서 평면 1px의 화면 폭
    s.y -= height * unit / k;
    vec2 ndc = vec2(s.x / size.x * 2.0 - 1.0, 1.0 - s.y / size.y * 2.0);
    gl_Position = vec4(ndc * p.z, 0.0, p.z);                 // w = z → 평면에서 원근 맞는 색 보간(빛기둥)
    v_color = color;
}
"""
GEO_FS = """
#version 120
varying vec4 v_color;
void main() { gl_FragColor = v_color; }
"""
TEX_VS = """
#version 120
attribute vec2 pos;        // 화면 논리 좌표
attribute vec2 uv;
attribute float alpha;
uniform vec2 size;
varying vec2 v_uv;
varying float v_alpha;
void main() {
    gl_Position = vec4(pos.x / size.x * 2.0 - 1.0, 1.0 - pos.y / size.y * 2.0, 0.0, 1.0);
    v_uv = uv;
    v_alpha = alpha;
}
"""
TEX_FS = """
#version 120
uniform sampler2D tex;
varying vec2 v_uv;
varying float v_alpha;
void main() { vec4 c = texture2D(tex, v_uv); gl_FragColor = vec4(c.rgb, c.a * v_alpha); }
"""


def available() -> bool:
    """실제 화면 + 데스크톱 OpenGL 2.1 이상일 때만. SCALERIFF_STAGE=cpu 면 끔(오프스크린 테스트는 항상 CPU)."""
    if os.environ.get("SCALERIFF_STAGE", "").lower() == "cpu":
        return False
    if QGuiApplication.platformName() not in ("windows", "xcb", "wayland", "cocoa"):
        return False
    ctx = QOpenGLContext()
    if not ctx.create() or ctx.isOpenGLES():
        return False
    fmt = ctx.format()
    return (fmt.majorVersion(), fmt.minorVersion()) >= (2, 1)


class HudWindow(QWidget):
    """GL 무대 위에 뜨는 투명 도구 창 — 네이티브 GL 창 밑에 가려지면 Qt가 그리지 않는 HUD 위젯(코드 표시·버튼·
    재생바·가이드·커튼)을 여기 올린다. Qt가 평소처럼 그리고 입력도 받는다. 투명한 곳 클릭은 아래 GL 창(건반)으로
    통과한다(레이어드 창). 앱 창에 딸려(위에 머묾·함께 최소화) 무대 자리를 따라다닌다. 포커스는 받지 않는다."""

    def __init__(self, anchor):
        super().__init__(anchor.window(), Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_WindowPropagation)   # 앱 글꼴·팔레트 물려받기
        self.anchor = anchor
        self.held = False                 # 커튼 동안 숨김(그동안 GL 무대가 이 창 그림을 대신 그린다)
        anchor.installEventFilter(self)
        anchor.window().installEventFilter(self)

    def eventFilter(self, obj, e):
        if obj is self.anchor and e.type() == e.Type.Show:   # 화면 진입은 그 화면이 커튼을 얹은 뒤 sync()
            return False
        if e.type() in (e.Type.Move, e.Type.Resize, e.Type.Show, e.Type.Hide, e.Type.WindowStateChange):
            self.sync()
        return False

    def hold(self, on):
        self.held = on
        self.sync()

    def sync(self):
        a = self.anchor
        if a.isVisible():                 # 숨겨 둔 동안에도 자리는 맞춘다(GL이 그릴 그림을 뜰 때 필요)
            self.setGeometry(QRect(a.mapToGlobal(QPoint(0, 0)), a.size()))
        show = a.isVisible() and not a.window().isMinimized() and not self.held
        if show != self.isVisible():
            self.setVisible(show)


def _rgba(c, alpha=None):
    a = c.alphaF() if alpha is None else min(255, int(alpha)) / 255
    return c.redF(), c.greenF(), c.blueF(), a


def _quad(corners, rgba):
    """평면 사각형(4점, 각 (x, y, 높이)) → 삼각형 2개 정점."""
    a, b, c, d = corners
    return [(*v, *rgba) for v in (a, b, c, a, c, d)]


class GLStage(QOpenGLWindow):
    def __init__(self, stage):
        super().__init__()
        fmt = QSurfaceFormat()
        fmt.setSwapInterval(1)            # vsync — 그리기를 화면 갱신에 맞춘다
        fmt.setSamples(0)                 # 멀티샘플은 내장 GPU에서 59 → 48fps(실측) — 선만 부드럽게
        self.setFormat(fmt)
        self.setFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)   # 키보드는 앱 창(스페이스 단축키)
        self.stage = stage
        self.ready = False
        self._tex = {}                    # 픽스맵 cacheKey → 텍스처
        self._sprites = OrderedDict()     # (상태, 건반, 발광색, 눌림) → (텍스처, 화면 사각형)
        self._dynamic = []                # 이번 프레임만 쓰는 텍스처(스플래시)
        self._scratch = None              # 건반별 그림을 그릴 화면 크기 그림(재사용)
        self._drop = False                # 창 크기 변경 → 텍스처 다시
        self.frame_ms = []                # 그리기 CPU 시간(측정용, 최근 600)
        self._mirrors = {}                # 대신 그리는 HUD 위젯 → [텍스처, 다시 그릴지]
        self.container = QWidget.createWindowContainer(self, stage)
        self.container.setGeometry(stage.rect())
        self.frameSwapped.connect(self._next)
        stage.gl = self

    # ── 무대가 부르는 것 ──────────────────────────────────────────
    def mirror(self, widget):
        """자주 바뀌는 HUD 위젯(코드 표시)을 GL이 대신 그린다 — HUD 창(레이어드 창)이 바뀔 때마다 Windows 화면 합성이
        다시 돌며 GL 화면 교체가 밀렸다(실측). 위젯은 HUD 창에 자리만 차지하고 widget.paint(p)로 그림을 준다."""
        self._mirrors[widget] = [None, True]

        def changed():
            self._mirrors[widget][1] = True
            self.update()
        widget.mirror = changed

    def resized(self):
        self.container.setGeometry(self.stage.rect())
        self._drop = True

    def _next(self):
        """재생 중엔 화면 갱신마다 다음 프레임(타이머와 무관하게 vsync 박자로)."""
        c = getattr(self.stage, "_curtain", None)
        if self.stage.driven or (c is not None and c.gl and c.running()):   # GL 커튼도 vsync마다
            self.update()

    def _disable(self, why):
        """GL이 안 되면 CPU 무대로 — 다음 이벤트 루프에서(그리기 콜백 안에서 창을 치우면 안 됨)."""
        print(f"[gl_stage] CPU 무대로 전환: {why}")
        traceback.print_exc()
        stage = self.stage

        def fall_back():
            if stage.gl is self:
                stage.gl = None
                self.container.hide()
                stage.update()
                for widget in self._mirrors:          # 대신 그리던 HUD 위젯은 다시 스스로 그린다
                    widget.mirror = None
                    widget.update()
        QTimer.singleShot(0, fall_back)

    # ── 입력: 건반 클릭은 무대로 ───────────────────────────────────
    def _forward(self, e):
        ev = QMouseEvent(e.type(), e.position(), e.globalPosition(), e.button(), e.buttons(), e.modifiers())
        QApplication.sendEvent(self.stage, ev)

    def mousePressEvent(self, e):
        w = self.stage                    # 클릭 포커스(스페이스 단축키) = 위젯 창에서 클릭한 것처럼
        while w is not None and not (w.focusPolicy() & Qt.FocusPolicy.ClickFocus):
            w = w.parentWidget()
        if w is not None:
            w.setFocus(Qt.FocusReason.MouseFocusReason)
        self._forward(e)

    def mouseReleaseEvent(self, e):
        self._forward(e)

    def mouseDoubleClickEvent(self, e):
        self._forward(e)

    # ── GL 준비 ──────────────────────────────────────────────────
    def initializeGL(self):
        try:
            prof = QOpenGLVersionProfile()
            prof.setVersion(2, 1)
            self.f = QOpenGLVersionFunctionsFactory.get(prof, self.context())
            if self.f is None:
                raise RuntimeError("OpenGL 2.1 함수 없음")
            self.geo = self._program(GEO_VS, GEO_FS)
            self.texp = self._program(TEX_VS, TEX_FS)
            self.vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            self.vbo.create()
            self.vbo.setUsagePattern(QOpenGLBuffer.UsagePattern.StreamDraw)
            self._loc = {(id(p), name): p.attributeLocation(name)
                         for p, names in ((self.texp, ("pos", "uv", "alpha")), (self.geo, ("plane", "height", "color")))
                         for name in names}
            self.ready = True
        except Exception as error:        # PyQt 가상함수 예외는 프로세스를 죽인다 → 잡아서 CPU로
            self._disable(error)

    def _program(self, vs, fs):
        p = QOpenGLShaderProgram(self)
        if not (p.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vs)
                and p.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fs) and p.link()):
            raise RuntimeError(p.log())
        return p

    def _texture(self, pix):
        tex = self._tex.get(pix.cacheKey())
        if tex is None:
            tex = self._tex[pix.cacheKey()] = self._make_texture(pix.toImage())
        return tex

    @staticmethod
    def _make_texture(image):
        tex = QOpenGLTexture(image, QOpenGLTexture.MipMapGeneration.DontGenerateMipMaps)
        tex.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
        tex.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        return tex

    def _drop_textures(self):
        for tex in list(self._tex.values()) + [t for t, _ in self._sprites.values()]:
            tex.destroy()
        for slot in self._mirrors.values():
            if slot[0] is not None:
                slot[0].destroy()
            slot[0] = None
        self._tex.clear()
        self._sprites.clear()

    def _upload(self, rows):
        arr = np.asarray(rows, dtype=np.float32)
        self.vbo.bind()
        self.vbo.allocate(arr.tobytes(), arr.nbytes)
        return len(arr)

    # ── 그리기 기본 ──────────────────────────────────────────────
    def _textured(self, tex, quads):
        """quads: [(화면 x0, y0, x1, y1, u0, v0, u1, v1, 불투명도)] — 텍스처 한 장으로 여러 사각형."""
        rows = []
        for x0, y0, x1, y1, u0, v0, u1, v1, a in quads:
            rows += [(x0, y0, u0, v0, a), (x1, y0, u1, v0, a), (x1, y1, u1, v1, a),
                     (x0, y0, u0, v0, a), (x1, y1, u1, v1, a), (x0, y1, u0, v1, a)]
        self._draw_tex(tex, rows)

    def _use(self, prog):
        """셰이더 바꾸기 — 정점 배치(속성 위치)는 바꿀 때만, 셰이더 값은 프레임당 한 번만
        (PyQt setUniformValue는 호출당 ~20µs: 그리기마다 넣으면 프레임에 1ms+)."""
        if self._bound is prog:
            return
        prog.bind()
        self._bound = prog
        if prog is self.texp:
            attrs, stride = (("pos", 0, 2), ("uv", 8, 2), ("alpha", 16, 1)), 20
        else:
            attrs, stride = (("plane", 0, 2), ("height", 8, 1), ("color", 12, 4)), 28
        for name, off, size in attrs:
            loc = self._loc[(id(prog), name)]
            prog.enableAttributeArray(loc)
            prog.setAttributeBuffer(loc, GL_FLOAT, off, size, stride)
        if prog in self._uniforms_set:
            return
        self._uniforms_set.append(prog)
        prog.setUniformValue("size", float(self.width()), float(self.height()))
        if prog is self.texp:
            prog.setUniformValue("tex", 0)
            return
        st = self.stage
        xf = st._xf
        s = -1.0 if xf.m33() < 0 else 1.0               # 동차좌표 부호를 z > 0으로(원근 보간용 w)
        for name, c in (("c0", (xf.m11(), xf.m12(), xf.m13())), ("c1", (xf.m21(), xf.m22(), xf.m23())),
                        ("c2", (xf.m31(), xf.m32(), xf.m33()))):
            prog.setUniformValue(name, s * c[0], s * c[1], s * c[2])
        prog.setUniformValue("k", float(st._unit(st._lane_h)))

    def _draw_tex(self, tex, rows):
        if not rows:
            return
        n = self._upload(rows)
        self._use(self.texp)
        tex.bind(0)
        self.f.glDrawArrays(GL_TRIANGLES, 0, n)

    def _image(self, pix, x, y, alpha=1.0):
        """구운 그림을 화면 논리 좌표 (x, y)에 원래 크기로."""
        dpr = pix.devicePixelRatio()
        self._textured(self._texture(pix), [(x, y, x + pix.width() / dpr, y + pix.height() / dpr,
                                             0, 0, 1, 1, alpha)])

    def _plane(self, rows, mode=GL_TRIANGLES):
        """평면 정점 [x, y, 높이, r, g, b, a]."""
        if not rows:
            return
        n = self._upload(rows)
        self._use(self.geo)
        self.f.glDrawArrays(mode, 0, n)

    def _blend(self, additive=False):
        self.f.glBlendFunc(GL_SRC_ALPHA, GL_ONE if additive else GL_ONE_MINUS_SRC_ALPHA)

    # ── 프레임 ───────────────────────────────────────────────────
    def paintGL(self):
        if not self.ready:
            return
        t0 = time.perf_counter()
        try:
            self._frame()
        except Exception as error:
            self.ready = False
            self._disable(error)
            return
        self.frame_ms = self.frame_ms[-599:] + [(time.perf_counter() - t0) * 1000]

    def _frame(self):
        st, f = self.stage, self.f
        if self._drop:
            self._drop_textures()
            self._drop = False
        for tex in self._dynamic:
            tex.destroy()
        self._dynamic = []
        self._bound, self._uniforms_set = None, []     # 셰이더 값은 이 프레임에 처음 쓸 때 한 번
        if st.driven and st.clock is not None:          # 그리는 순간의 재생 위치(타이머 틱보다 정확)
            sec, beat = st.clock()
            st.riff.set_position(sec)
            st.beat = beat
        key = st._key_state()
        if key not in st._caches:                       # 진입·창 크기 변경 뒤 첫 프레임 = 곡 전체 건반 층
            st._build_caches()
        if st._bg is None:
            st._bg = st._build_bg()
        dpr = self.devicePixelRatio()
        f.glViewport(0, 0, round(self.width() * dpr), round(self.height() * dpr))
        f.glClearColor(0, 0, 0, 1)
        f.glClear(GL_COLOR_BUFFER_BIT)
        f.glEnable(GL_BLEND)
        self._blend()
        self._back()
        glows, scene = st._scene()
        self._lane(glows, scene)
        self._keys(glows)
        self._splashes()
        self._sparkles(scene)
        self._draw_mirrors()
        self._overlay()

    def _draw_mirrors(self):
        st, dpr = self.stage, self.devicePixelRatio()
        for widget, slot in self._mirrors.items():
            if not widget.isVisibleTo(widget.window()):  # HUD 창이 커튼 동안 숨어 있어도 그린다
                continue
            if slot[1] or slot[0] is None:            # 바뀐 프레임에만 다시 떠서 올린다(작은 그림)
                img = QImage(round(widget.width() * dpr), round(widget.height() * dpr),
                             QImage.Format.Format_ARGB32_Premultiplied)
                img.setDevicePixelRatio(dpr)
                img.fill(Qt.GlobalColor.transparent)
                p = QPainter(img)
                widget.paint(p)
                p.end()
                if slot[0] is not None:
                    slot[0].destroy()
                slot[0], slot[1] = self._make_texture(img), False
            at = st.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
            self._textured(slot[0], [(at.x(), at.y(), at.x() + widget.width(), at.y() + widget.height(),
                                      0, 0, 1, 1, 1.0)])

    def _overlay(self):
        """HUD 창 그림(커튼 동안 숨긴 HUD 대신) + GL 커튼(떠난 화면 그림·천) — 한 창이 vsync로 그려 층 순서·박자가
        어긋나지 않는다(HUD 투명 창은 한 장에 30~90ms라 커튼이 끊기고, 두 창은 화면에 따로 올라간다)."""
        st = self.stage
        if st.hud_snap is not None:
            self._image(st.hud_snap, 0, 0)
        c = getattr(st, "_curtain", None)
        if c is None or not c.gl:
            return
        c.frame()
        if not c.running():                              # 시작 전(로딩): 천 텍스처를 미리 올려 둔다(첫 업로드가 수백 ms 멈춤)
            for left in (True, False):
                for pix in (c.fabric(left), c.cast[0 if left else 1]):
                    self._textured(self._texture(pix), [(0, 0, 1, 1, 0, 0, 1, 1, 0.0)])
        if c.cover is not None:
            pix, origin = c.cover
            at = st.mapFromGlobal(origin)
            self._image(pix, at.x(), at.y())
        w = c.width()
        for left in (True, False):
            pix, cast = c.fabric(left), c.cast[0 if left else 1]
            rows, dpr = pix.height(), pix.devicePixelRatio()
            cloth, shade = [], []
            for i, e in enumerate(c.profile):                # Curtain._Cloth와 같은 띠 — 띠마다 안쪽 가장자리까지 늘림
                r0, r1 = round(rows * i / S_STRIPS), round(rows * (i + 1) / S_STRIPS)
                if e <= 0.5 or r1 <= r0:
                    continue
                x, y0, y1 = 0 if left else w - e, r0 / dpr, r1 / dpr
                cloth.append((x, y0, x + e, y1, 0, r0 / rows, 1, r1 / rows, c.alpha))
                cw = min(CAST, e)
                sx = x + e - cw if left else x
                shade.append((sx, y0, sx + cw, y1, 0, 0, 1, 1, c.alpha))
            self._textured(self._texture(pix), cloth)
            self._textured(self._texture(cast), shade)

    def _back(self):
        """배경 + 아지랑이(재생 중에도 흐름 — GPU라 공짜) + 소실점 박 펄스. 안개·펄스는 판정선 위 무대 벽·바닥에만:
        판정선 위로 자르고(scissor) 그린 뒤 도로(레인 사다리꼴)를 배경에서 다시 덮는다(= Stage._haze의 그릴 영역)."""
        st, f = self.stage, self.f
        self._image(st._bg, 0, 0)
        if reduced_motion():
            return
        if st._haze is None:
            st._haze = st._build_haze()
        layers, glow, r, _ = st._haze
        t, w, h = time.perf_counter(), st.width(), st.height()
        dpr = self.devicePixelRatio()
        top = round(h * S.KEYS_TOP * dpr)
        f.glEnable(GL_SCISSOR_TEST)
        f.glScissor(0, round(h * dpr) - top, round(w * dpr), top)
        self._blend(additive=True)                      # 빛은 더해진다(Plus)
        for i, (layer, rise, period) in enumerate(layers):
            off = (t * rise * h) % h                    # 위로 흐름(두 장 이어 그려 빈틈 없음)
            breathe = 0.5 + 0.5 * math.sin(2 * math.pi * t / period + i * 2.1)
            sway = w * 0.02 * (math.sin(2 * math.pi * t / (period * 1.6) + i) - 1)
            lw, lh = layer.width() / dpr, layer.height() / dpr
            a = 0.35 + 0.45 * breathe
            self._textured(self._texture(layer), [(sway, -off, sway + lw, -off + lh, 0, 0, 1, 1, a),
                                                  (sway, h - off, sway + lw, h - off + lh, 0, 0, 1, 1, a)])
        c = st._xf.map(QPointF(w / 2, 0))
        self._image(glow, c.x() - r, c.y() - r, min(1.0, 0.25 + 0.75 * st._pulse()))
        self._blend()
        lane = st._xf.map(QPolygonF(QRectF(0, 0, w, st._lane_h)))   # 도로는 배경 그대로
        bw, bh = st._bg.width() / dpr, st._bg.height() / dpr
        rows = [(q.x(), q.y(), q.x() / bw, q.y() / bh, 1.0) for q in (lane[0], lane[1], lane[2], lane[0], lane[2], lane[3])]
        self._draw_tex(self._texture(st._bg), rows)
        f.glDisable(GL_SCISSOR_TEST)

    def _lane(self, glows, scene):
        """레인: 프로그램 차례 마디 어둡게 · 박자·코드선 · 점선 · 직육면체(번짐·면) · 노드 모서리 선 · 빛기둥."""
        st, riff, f = self.stage, self.stage.riff, self.f
        w, lane = st.width(), st._lane_h
        tris = []
        for top, bottom in riff.call_bands():
            tris += _quad([(0, top, 0), (w, top, 0), (w, bottom, 0), (0, bottom, 0)], _rgba(S.CALL_DIM))
        self._plane(tris)
        f.glEnable(GL_LINE_SMOOTH)
        dpr = self.devicePixelRatio()
        chord = riff._lines(riff._chord_grid) if riff._chord_grid else []
        for lines, alpha, width in ((riff._lines(), 22, 1.0), (chord, S.CHORD_LINE.alpha(), 1.5)):
            rows = []
            for y, when in lines:                       # 키 밖 코드 구간 = 같은 밝기의 옅은 주황
                rgba = _rgba(QColor(T.DETOUR) if riff.in_detour(when) else QColor(255, 255, 255), alpha)
                rows += [(0, y, 0, *rgba), (w, y, 0, *rgba)]
            f.glLineWidth(width * dpr)
            self._plane(rows, GL_LINES)
        tris = self._dashes()
        rims = []
        k = st._unit(lane)
        inv = st._kinv
        for x, size, y0, y1, lift, color, alpha, solid, _ in scene:
            c = QColor(color)
            lip = st._lip()
            lo, hi = lift, lift + lip
            l, r = x - size / 2, x + size / 2
            xs = r if x < w / 2 else l                  # 가운데 쪽 옆면만 보인다
            if solid:
                side, top, front = st._block(x, size, y0, y1, lift, k)
                if color != S.TONE_SCALE:               # 색 노드 = 같은 색으로 은은히 번짐(면 아래)
                    tris += self._halo([top[0], top[1], front[2], front[3]], c)
                shades = (c.darker(170), c, c.darker(115))
            else:
                shades = (c.darker(170), c, c.darker(140))
            tris += _quad([(xs, y0, hi), (xs, y1, hi), (xs, y1, lo), (xs, y0, lo)], _rgba(shades[0], alpha * 1.3))
            tris += _quad([(l, y0, hi), (r, y0, hi), (r, y1, hi), (l, y1, hi)], _rgba(shades[1], alpha))
            tris += _quad([(l, y1, hi), (r, y1, hi), (r, y1, lo), (l, y1, lo)], _rgba(shades[2], alpha * 1.5))
            if solid:                                   # 밝은 모서리(윗면 둘레·앞면 테두리)
                rim = c.lighter(175)
                for poly, a in ((top, 220), (front, 120)):
                    rgba = _rgba(rim, a)
                    pts = [inv.map(q) for q in poly]
                    for i in range(4):
                        rims += [(pts[i].x(), pts[i].y(), 0, *rgba), (pts[(i + 1) % 4].x(), pts[(i + 1) % 4].y(), 0, *rgba)]
        for midi, c in glows.items():                   # 건반에서 레인 위로 빛기둥(아래 120 → 위 0)
            kr = st._key_rect(midi)
            y0 = lane * (1 - S.BEAM)
            near, far = _rgba(c, 120), _rgba(c, 0)
            tris += [(kr.left(), y0, 0, *far), (kr.right(), y0, 0, *far), (kr.right(), lane, 0, *near),
                     (kr.left(), y0, 0, *far), (kr.right(), lane, 0, *near), (kr.left(), lane, 0, *near)]
        self._plane(tris)
        f.glLineWidth(dpr)
        self._plane(rims, GL_LINES)
        f.glDisable(GL_LINE_SMOOTH)

    def _dashes(self):
        """레일 바깥 흐르는 점선(Stage._draw_dashes와 같은 자리·밝기)."""
        st = self.stage
        w, lane = st.width(), st._lane_h
        gap, length, depth = w * S.DASH_X, w * S.DASH_LEN, lane * S.DASH_DEPTH
        c = QColor(T.NEON_LIGHT)
        out = []
        for y, on_beat in st.riff.dash_lines(S.DASH_PER_BEAT):
            rgba = _rgba(c, (230 if on_beat else 130) * min(1.0, 0.25 + y / lane))
            for x in (-gap - length, w + gap):
                out += _quad([(x, y - depth, 0), (x + length, y - depth, 0), (x + length, y, 0), (x, y, 0)], rgba)
        return out

    def _halo(self, poly, color):
        """노드 둘레 번짐 띠(화면에서 바깥으로 HALO_RINGS) → 역변환한 평면 점(높이 0)."""
        n = len(poly)
        cx = sum(q.x() for q in poly) / n
        cy = sum(q.y() for q in poly) / n
        inv = self.stage._kinv
        out, inner = [], 0.0
        for dist, alpha in HALO_RINGS:
            rgba = _rgba(color, 255 * alpha * S.NOTE_GLOW / 1.5)
            ring = []
            for d in (inner, dist):                     # 꼭짓점을 중심 반대쪽으로 d만큼(볼록 사각형 근사)
                pts = []
                for q in poly:
                    dx, dy = q.x() - cx, q.y() - cy
                    ln = math.hypot(dx, dy) or 1.0
                    pts.append(inv.map(QPointF(q.x() + dx / ln * d, q.y() + dy / ln * d)))
                ring.append(pts)
            a, b = ring
            for i in range(n):
                j = (i + 1) % n
                out += _quad([(a[i].x(), a[i].y(), 0), (a[j].x(), a[j].y(), 0),
                              (b[j].x(), b[j].y(), 0), (b[i].x(), b[i].y(), 0)], rgba)
            inner = dist
        return out

    def _keys(self, glows):
        """건반 층(상태별 구운 그림) — 눌림·발광 건반이 지나는 세로 띠(Stage._strips와 같은 자리)만 그 안의 건반들을
        건반별 그림으로 흰 건반 → 흑건 순서로 다시 얹는다(띠 밖은 잘라냄 = CPU의 띠 클립과 같은 그림).
        경계는 실제 픽셀에 맞춘다(논리 좌표로 반올림하면 배율 125%에서 1px 틈이 보였음)."""
        st, f = self.stage, self.f
        pos, cache = st._caches[st._key_state()]
        dpr = cache.devicePixelRatio()
        cw, ch = cache.width() / dpr, cache.height() / dpr
        area = st._keys_area()
        cuts = []
        for midi in glows:                              # 띠 x 구간(실제 픽셀) — 겹치면 합침
            box = st._key_box(midi)
            a = int(box.left())
            cuts.append([math.floor(a * dpr), math.ceil((a + int(box.width()) + 2) * dpr)])
        cuts.sort()
        merged = []
        for a, b in cuts:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        Y0, Y1 = math.floor(area.top() * dpr), math.ceil((area.bottom() + 1) * dpr)
        y0, y1 = Y0 / dpr, Y1 / dpr
        v0, v1 = (y0 - pos.y()) / ch, (y1 - pos.y()) / ch
        quads, X = [], math.floor(area.left() * dpr)
        for A, B in merged + [[math.ceil((area.right() + 1) * dpr)] * 2]:
            if A > X:
                x0, x1 = X / dpr, A / dpr
                quads.append((x0, y0, x1, y1, (x0 - pos.x()) / cw, v0, (x1 - pos.x()) / cw, v1, 1.0))
            X = max(X, B)
        self._textured(self._texture(cache), quads)
        if not merged:
            return
        pressed = st.piano._pressed
        whites, blacks = st._keys()
        fb_h = round(self.height() * dpr)
        f.glEnable(GL_SCISSOR_TEST)
        for A, B in merged:
            f.glScissor(A, fb_h - Y1, B - A, Y1 - Y0)
            strip = QRectF(A / dpr, y0, (B - A) / dpr, y1 - y0)
            for midi in whites + blacks:
                if strip.intersects(st._key_box(midi)):
                    tex, r = self._key_sprite(midi, glows.get(midi), midi in pressed, Y0, Y1)
                    self._textured(tex, [(r.left(), r.top(), r.right(), r.bottom(), 0, 0, 1, 1, 1.0)])
        f.glDisable(GL_SCISSOR_TEST)

    def _key_sprite(self, midi, glow, pressed, Y0, Y1):
        """건반 하나(그림자·발광·번호 포함)를 투명 그림에 — (상태, 건반, 발광색, 눌림)별로 한 번만 CPU로 그린다."""
        st = self.stage
        key = (st._key_state(), midi, glow.rgba() if glow is not None else 0, pressed)
        hit = self._sprites.pop(key, None)
        if hit is None:
            dpr = self.devicePixelRatio()
            box = st._key_box(midi)
            dev = QRect(math.floor(box.left() * dpr), Y0,
                        math.ceil(box.right() * dpr) - math.floor(box.left() * dpr), Y1 - Y0)
            size = (round(st.width() * dpr) + 2, round(st.height() * dpr) + 2)
            img = self._scratch                         # 건반 그리기는 화면 좌표 그대로 → 화면 크기 그림 하나를 재사용
            if img is None or (img.width(), img.height()) != size:
                img = self._scratch = QImage(*size, QImage.Format.Format_ARGB32_Premultiplied)
                img.setDevicePixelRatio(dpr)
            logical = QRectF(dev.x() / dpr, dev.y() / dpr, dev.width() / dpr, dev.height() / dpr)
            p = QPainter(img)
            p.setClipRect(logical)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(logical, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            st._draw_keys(p, {midi: glow} if glow is not None else {}, {midi} if pressed else set(), {midi})
            p.end()
            hit = (self._make_texture(img.copy(dev)), logical)
            if len(self._sprites) >= SPRITE_CACHE:
                self._sprites.popitem(last=False)[1][0].destroy()
        self._sprites[key] = hit
        return hit

    def _splashes(self):
        """리프 타격 스플래시 — 살아 있는 동안 작은 그림에 CPU로 그려 올린다(동시에 몇 개뿐)."""
        st = self.stage
        areas = st._live_splashes()
        if not areas:
            return
        box = QRect(areas[0])
        for a in areas[1:]:
            box = box.united(a)
        dpr = self.devicePixelRatio()
        img = QImage(round(box.width() * dpr) + 1, round(box.height() * dpr) + 1,
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        st._draw_splashes(p, QPointF(box.topLeft()))
        p.end()
        tex = self._make_texture(img)
        self._dynamic.append(tex)
        self._textured(tex, [(box.left(), box.top(), box.left() + img.width() / dpr, box.top() + img.height() / dpr,
                              0, 0, 1, 1, 1.0)])

    def _sparkles(self, scene):
        """근음 별빛(건반 앞면 + 근음 노드 앞면) — 별 그림 한 장을 크기·밝기만 바꿔 찍는다."""
        st = self.stage
        k = st._unit(st._lane_h)
        targets = [(st._block(x, size, y0, y1, lift, k)[2], seed)
                   for x, size, y0, y1, lift, color, _, solid, seed in scene if solid and color == S.TONE_ROOT]
        stars = st._sparkle_stars(targets + st._root_fronts())
        if not stars:
            return
        quads = [(c.x() - size, c.y() - size, c.x() + size, c.y() + size, 0, 0, 1, 1, alpha)
                 for c, size, alpha in stars]           # 별 그림 = 크기 SPARKLE_SIZE 별을 2배 상자에 → 상자 반폭 = 크기
        self._textured(self._star_sprite(), quads)

    def _star_sprite(self):
        tex = self._tex.get("star")
        if tex is None:
            scale = 4 * self.devicePixelRatio()          # 크게 그려 줄여 쓴다(작은 별도 매끈)
            n = round(2 * S.SPARKLE_SIZE * scale)
            img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(Qt.GlobalColor.transparent)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.scale(scale, scale)
            S.Stage._star(p, QPointF(S.SPARKLE_SIZE, S.SPARKLE_SIZE), S.SPARKLE_SIZE, 1.0)
            p.end()
            tex = self._tex["star"] = self._make_texture(img)
        return tex
