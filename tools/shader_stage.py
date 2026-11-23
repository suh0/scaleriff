"""GPU 시험판 셰이더 층(tools/gl_trial.py shader) — 무대(Stage)를 모델로 두고 그 위를 덮어 그린다.

매 프레임 파이썬은 보이는 박자선·점선·코드 색 띠를 평면 좌표 정점 배열로 만들어 올리기만 하고, 원근 변환과
직육면체 두께(Stage._block과 같은 식)는 정점 셰이더가 계산한다. 배경·건반 층은 Stage가 구운 그림을 텍스처로.
범위: 자유연습(리프 노드·번짐·별빛·눌린 건반·빛기둥·아지랑이·펄스 클립 없음) — 비용 비교용.
"""
import time

import numpy as np
from PyQt6.QtCore import QEvent, QObject, QPointF, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtOpenGL import (QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLTexture,
                            QOpenGLVersionFunctionsFactory, QOpenGLVersionProfile)
from PyQt6.QtOpenGL import QOpenGLWindow
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QWidget

from gui import theme as T
from gui.widgets import stage as S

GL_FLOAT, GL_TRIANGLES, GL_LINES = 0x1406, 0x0004, 0x0001
GL_BLEND, GL_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA = 0x0BE2, 0x0302, 1, 0x0303
GL_COLOR_BUFFER_BIT = 0x4000

GEO_VS = """
#version 120
attribute vec2 plane;      // 평면 좌표(레인)
attribute float height;    // 판정선 기준 화면 px 높이(Stage._block의 lift·lift+lip)
attribute vec4 color;
uniform vec3 c0, c1, c2;   // QTransform 열: 화면 = (x*c0 + y*c1 + c2).xy / z
uniform vec2 size;         // 위젯 논리 크기
uniform float k;           // 판정선 깊이에서 평면 1px의 화면 폭
varying vec4 v_color;
void main() {
    vec3 p = plane.x * c0 + plane.y * c1 + c2;
    vec2 s = p.xy / p.z;
    float unit = (c0.x * p.z - p.x * c0.z) / (p.z * p.z);   // 이 깊이에서 평면 1px의 화면 폭
    s.y -= height * unit / k;
    gl_Position = vec4(s.x / size.x * 2.0 - 1.0, 1.0 - s.y / size.y * 2.0, 0.0, 1.0);
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
attribute vec2 pos;
attribute vec2 uv;
uniform vec2 size;
varying vec2 v_uv;
void main() {
    gl_Position = vec4(pos.x / size.x * 2.0 - 1.0, 1.0 - pos.y / size.y * 2.0, 0.0, 1.0);
    v_uv = uv;
}
"""
TEX_FS = """
#version 120
uniform sampler2D tex;
uniform float opacity;
varying vec2 v_uv;
void main() { gl_FragColor = texture2D(tex, v_uv) * vec4(1.0, 1.0, 1.0, opacity); }
"""


def _rgba(c, alpha):
    return (c.redF(), c.greenF(), c.blueF(), min(255, int(alpha)) / 255)


class _Follow(QObject):
    """무대 크기가 바뀌면 셰이더 층도 같이."""

    def __init__(self, layer):
        super().__init__(layer)
        self.layer = layer

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Resize:
            self.layer.setGeometry(obj.rect())
        return False


class _Renderer:
    """셰이더 그리기(QOpenGLWidget·QOpenGLWindow 공통)."""

    # ── GL 준비 ──────────────────────────────────────────────────
    def initializeGL(self):
        prof = QOpenGLVersionProfile()
        prof.setVersion(2, 1)
        self.f = QOpenGLVersionFunctionsFactory.get(prof, self.context())
        self.geo = self._program(GEO_VS, GEO_FS)
        self.texp = self._program(TEX_VS, TEX_FS)
        self.vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
        self.vbo.create()
        self.vbo.setUsagePattern(QOpenGLBuffer.UsagePattern.StreamDraw)

    def _program(self, vs, fs):
        p = QOpenGLShaderProgram(self)
        assert p.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vs), p.log()
        assert p.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fs), p.log()
        assert p.link(), p.log()
        return p

    def _texture(self, pix):
        tex = self._tex.get(pix.cacheKey())
        if tex is None:
            tex = self._tex[pix.cacheKey()] = QOpenGLTexture(pix.toImage())
            tex.setMinMagFilters(QOpenGLTexture.Filter.Linear, QOpenGLTexture.Filter.Linear)
        return tex

    def _upload(self, data):
        arr = np.ascontiguousarray(data, dtype=np.float32)
        self.vbo.bind()
        self.vbo.allocate(arr.tobytes(), arr.nbytes)
        return arr

    # ── 그리기 ───────────────────────────────────────────────────
    def _quad(self, pix, x, y, opacity=1.0):
        """구운 그림을 논리 좌표 (x, y)에 원래 크기로."""
        dpr = pix.devicePixelRatio()
        w, h = pix.width() / dpr, pix.height() / dpr
        v = [x, y, 0, 0, x + w, y, 1, 0, x + w, y + h, 1, 1, x, y, 0, 0, x + w, y + h, 1, 1, x, y + h, 0, 1]
        self._upload(v)
        p = self.texp
        p.bind()
        p.setUniformValue("size", float(self.width()), float(self.height()))
        p.setUniformValue("opacity", float(opacity))
        p.setUniformValue("tex", 0)
        self._texture(pix).bind(0)
        for name, off, n in (("pos", 0, 2), ("uv", 8, 2)):
            loc = p.attributeLocation(name)
            p.enableAttributeArray(loc)
            p.setAttributeBuffer(loc, GL_FLOAT, off, n, 16)
        self.f.glDrawArrays(GL_TRIANGLES, 0, 6)

    def _geometry(self, verts, mode):
        """verts: [x, y, height, r, g, b, a] 행들."""
        if not verts:
            return
        arr = self._upload(verts)
        p, st = self.geo, self.stage
        p.bind()
        xf = st._xf
        p.setUniformValue("c0", xf.m11(), xf.m12(), xf.m13())
        p.setUniformValue("c1", xf.m21(), xf.m22(), xf.m23())
        p.setUniformValue("c2", xf.m31(), xf.m32(), xf.m33())
        p.setUniformValue("size", float(self.width()), float(self.height()))
        p.setUniformValue("k", float(st._unit(st._lane_h)))
        for name, off, n in (("plane", 0, 2), ("height", 8, 1), ("color", 12, 4)):
            loc = p.attributeLocation(name)
            p.enableAttributeArray(loc)
            p.setAttributeBuffer(loc, GL_FLOAT, off, n, 28)
        self.f.glDrawArrays(mode, 0, len(arr))

    def paintGL(self):
        t0 = time.perf_counter()
        st, f = self.stage, self.f
        key = st._key_state()                        # 캐시는 Stage가 굽는다(진입 첫 프레임에 곡 전체)
        if key not in st._caches:
            st._build_caches()
        if st._bg is None:
            st._bg = st._build_bg()
        if st._haze is None:
            st._haze = st._build_haze()
        f.glClearColor(0, 0, 0, 1)
        f.glClear(GL_COLOR_BUFFER_BIT)
        f.glEnable(GL_BLEND)
        f.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self._quad(st._bg, 0, 0)
        _, glow, r, _ = st._haze                    # 소실점 박 펄스(빛은 더한다)
        f.glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        c = st._xf.map(QPointF(st.width() / 2, 0))
        self._quad(glow, c.x() - r, c.y() - r, min(1.0, 0.25 + 0.75 * st._pulse()))
        f.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        self._geometry(self._lines(), GL_LINES)
        self._geometry(self._dashes() + self._bands(), GL_TRIANGLES)
        pos, cache = st._caches[st._key_state()]
        self._quad(cache, pos.x(), pos.y())
        self.paints.append((t0, time.perf_counter()))

    # ── 정점 만들기(평면 좌표) ───────────────────────────────────
    def _lines(self):
        st, riff, w = self.stage, self.stage.riff, self.stage.width()
        out = []
        chord = riff._lines(riff._chord_grid) if riff._chord_grid else []
        for lines, alpha in ((riff._lines(), 22), (chord, S.CHORD_LINE.alpha())):
            for y, when in lines:
                c = QColor(T.DETOUR) if riff.in_detour(when) else QColor(255, 255, 255)
                rgba = _rgba(c, alpha)
                out += [(0, y, 0, *rgba), (w, y, 0, *rgba)]
        return out

    def _dashes(self):
        st = self.stage
        w, lane = st.width(), st._lane_h
        gap, length, depth = w * S.DASH_X, w * S.DASH_LEN, lane * S.DASH_DEPTH
        c = QColor(T.NEON_LIGHT)
        out = []
        for y, on_beat in st.riff.dash_lines(S.DASH_PER_BEAT):
            rgba = _rgba(c, (230 if on_beat else 130) * min(1.0, 0.25 + y / lane))
            for x in (-gap - length, w + gap):
                out += self._quad_verts([(x, y - depth, 0), (x + length, y - depth, 0),
                                         (x + length, y, 0), (x, y, 0)], rgba)
        return out

    @staticmethod
    def _quad_verts(corners, rgba):
        a, b, c, d = corners
        return [(*v, *rgba) for v in (a, b, c, a, c, d)]

    def _bands(self):
        """Stage.paintEvent의 자유연습 코드 색 띠와 같은 면·색·순서(옆 → 윗 → 앞, 먼 것부터)."""
        st, piano = self.stage, self.stage.piano
        kw, lip = piano._geometry()[3], st._lip()
        rise = lip * S.BLACK_RISE
        blocks = []
        for x, y, size, length, color in st.riff.chord_bands():
            y0, y1 = max(0.0, y), min(st._lane_h, y + length)
            if y0 < y1:
                lift = (0.0 if size >= kw - 1e-6 else rise) - lip
                blocks.append(((y1, lift, -abs(x - st.width() / 2)), x, size, y0, y1, lift, color))
        out = []
        for _, x, size, y0, y1, lift, color in sorted(blocks, key=lambda b: b[0]):
            alpha = S.BAND_ALPHA[color]
            c = QColor(color)
            lo, hi = lift, lift + lip
            l, r = x - size / 2, x + size / 2
            xs = r if x < st.width() / 2 else l
            out += self._quad_verts([(xs, y0, hi), (xs, y1, hi), (xs, y1, lo), (xs, y0, lo)],
                                    _rgba(c.darker(170), alpha * 1.3))
            out += self._quad_verts([(l, y0, hi), (r, y0, hi), (r, y1, hi), (l, y1, hi)], _rgba(c, alpha))
            out += self._quad_verts([(l, y1, hi), (r, y1, hi), (r, y1, lo), (l, y1, lo)],
                                    _rgba(c.darker(140), alpha * 1.5))
        return out


class ShaderLayer(_Renderer, QOpenGLWidget):
    """위젯 합성: 무대 위 자식 위젯(HUD가 위에 겹침, 창 전체를 Qt가 GPU로 합성)."""

    def __init__(self, stage, paints):
        super().__init__(stage)
        self.stage, self.paints = stage, paints
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        stage.installEventFilter(_Follow(self))
        self.setGeometry(stage.rect())
        self._tex = {}                               # 픽스맵 cacheKey → 텍스처


class NativeLayer(_Renderer, QOpenGLWindow):
    """네이티브 GL 창(창 컨테이너): 위젯 합성 없음 — 대신 HUD 위젯이 이 창 밑에 가려진다(측정용)."""

    def __init__(self, stage, paints):
        super().__init__()
        self.stage, self.paints = stage, paints
        self._tex = {}
        self.container = QWidget.createWindowContainer(self, stage)
        stage.installEventFilter(_Follow(self.container))
        self.container.setGeometry(stage.rect())
        self.container.show()
