"""연주 무대 — 건반과 노드 레인을 원근(3D로 기울인 하이웨이)으로 그린다.

평면 좌표(world): 레인 y∈[0, lane_h], 건반 y∈[lane_h, lane_h+kh], x는 PianoWidget 좌표 그대로.
원근 변환 하나(평면 → 화면 사다리꼴, 참고 이미지 실측 비율)를 레인과 건반이 함께 쓴다:
건반 양옆이 레일 기울기 그대로 이어지고, 넓어진 건반 앞쪽이 화면에 들어오도록 무대 전체를 축소한다.

연주 중 비용: 벽·도로·레인 선·눌리지 않은 건반·앞면 상태색은 QPixmap 캐시
(창 크기·스케일이 바뀔 때만 다시 그림). 매 프레임엔 캐시 복사 + 노드·눌린 건반·빛기둥·예고만 그린다.
건반 클릭은 역변환 한 번 → PianoWidget._midi_at, 다시 그리기는 바뀐 건반 영역만(update_keys).
"""
import math
import random
import time

from PyQt6.QtCore import Qt, QPointF, QRectF, QTimer
from PyQt6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap,
                         QPolygonF, QTransform)
from PyQt6.QtWidgets import QWidget

from gui import theme as T
from gui.widgets.piano import (BLACK_L, BLACK_PCS, BLACK_W, MIDI_HIGH, MIDI_LOW, PREVIEW_SPACE,
                               WHITE_RATIO, _is_white, black_x)

# 참고 이미지 실측(화면 비율): 레인 먼 끝 y≈0.13·폭≈0.18, 판정선 y≈0.64, 건반 앞 y≈0.93, 앞면 ≈0.033
TOP_Y = 0.13       # 레인 먼 끝의 화면 높이 비율
TOP_WIDTH = 0.34   # 레인 먼 끝의 폭(화면 폭 비율) = 시점 높이: 클수록 위에서 내려다본 원근(이미지는 0.18)
KEYS_TOP = 0.64    # 건반 윗선(판정선)의 화면 높이 비율
KEYS_BOTTOM = 0.925  # 건반 윗면 앞 모서리의 화면 높이 비율(그 아래 앞면 두께)
LIP = 0.06         # 흰 건반 앞면 두께(화면 높이 비율) — 건반 높이
BLACK_RISE = 0.65  # 흑건이 흰 건반 윗면보다 솟은 높이(흰 건반 앞면 두께 대비, 실측 12.7mm/≈20mm)
DIP = 0.42         # 눌림 깊이(흰 건반 앞면 두께 대비, 실측 10mm) — 뒤쪽 축 기준으로 앞이 내려감
RAIL = 0.022       # 도로 양옆 레일 폭(평면 폭 비율)
BEAM = 0.45        # 빛기둥 길이(레인 길이 비율)
CHORD_LINE = QColor(255, 255, 255, 90)   # 코드 전환선(박자선보다 밝게)

# 근음·코드톤·스케일음 = 같은 파란 계열, 진하기로 구분(앞면·노드·눌림 공통)
TONE_ROOT = "#1f4bff"    # 진함 + 형광(채도·밝기 높임)
TONE_CHORD = "#3b82f6"   # 중간
TONE_SCALE = "#93c5fd"   # 연함
ROOT_GLOW = 0.8         # 근음 발광(글로우) 세기 0~1
SPARKLE_COUNT = 4       # 근음 건반·노드마다 반짝이 개수
SPARKLE_SPEED = 1.6     # 반짝이 깜빡임 속도(Hz)
WALL_TONES = ("#161d28", "#1c2532", "#121822")


def _quad(rect, corners):
    """평면 사각형 → 화면 사각형(좌상·우상·우하·좌하) 원근 변환."""
    xf = QTransform()
    QTransform.quadToQuad(QPolygonF([rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft()]),
                          QPolygonF([QPointF(x, y) for x, y in corners]), xf)
    return xf


def _hair(color, width=1.0):
    """원근 변환과 무관하게 화면에서 일정한 두께의 선."""
    pen = QPen(color, width)
    pen.setCosmetic(True)
    return pen


class Stage(QWidget):
    def __init__(self, piano, riff, parent=None):
        super().__init__(parent)
        self.piano, self.riff = piano, riff
        piano.setParent(self)
        piano.hide()                       # 상태·기하 모델로만 사용
        riff.setParent(self)
        riff.hide()
        self.setMinimumHeight(240)
        self._xf = QTransform()            # 레인(평면 → 화면)
        self._kxf = QTransform()           # 건반(평면 → 화면)
        self._kinv = QTransform()
        self._lane_h = 1.0
        self._scale = 1.0                  # 화면 맞춤 축소 비율
        self._cache = None
        self._cache_key = None
        self.cache_builds = 0              # 캐시 재생성 횟수(비용 측정용)
        self._mouse_midi = None
        # 근음 "샤랄라" 반짝이: 근음이 보일 때만 ~30fps로 그 영역만 다시 그림
        self._sparkle_areas = []
        self._sparkle_timer = QTimer(self)
        self._sparkle_timer.setInterval(33)
        self._sparkle_timer.timeout.connect(
            lambda: [self.update(r) for r in self._sparkle_areas])

    # ── 기하 ─────────────────────────────────────────────────────
    def resizeEvent(self, e):
        super().resizeEvent(e)
        w, h = self.width(), self.height()
        kw = w / 14
        self.piano.resize(w, int(kw * WHITE_RATIO) + PREVIEW_SPACE)
        _, _, _, _, kh = self.piano._geometry()
        half, hit = w * TOP_WIDTH / 2, h * KEYS_TOP
        trap = [(w / 2 - half, h * TOP_Y), (w / 2 + half, h * TOP_Y), (w, hit), (0, hit)]
        # 레인 평면을 건반까지 연장했을 때 건반 앞 모서리가 KEYS_BOTTOM에 오도록 레인 길이를 정한다
        probe, _ = _quad(QRectF(0, 0, w, 1), trap).inverted()
        t = probe.map(QPointF(w / 2, h * KEYS_BOTTOM)).y()        # 레인 길이 1 기준 평면 깊이(>1)
        self._lane_h = kh / (t - 1)
        self.riff.resize(w, max(1, int(self._lane_h)))
        xf = _quad(QRectF(0, 0, w, self._lane_h), trap)
        # 레일 기울기로 넓어진 건반 앞쪽(앞면 포함)이 좌우 여백 안에 들도록 아래 가운데 기준으로 전체 축소
        left = xf.map(QPointF(0, self._lane_h + kh)).x()
        bottom = h * (KEYS_BOTTOM + LIP)
        self._scale = min(1.0, (w - 2 * T.PAD_H) / (w - 2 * left))
        fit = QTransform().translate(w / 2, bottom).scale(self._scale, self._scale).translate(-w / 2, -bottom)
        self._xf = self._kxf = xf * fit
        self._kinv, _ = self._kxf.inverted()
        self._cache_key = None

    def _key_rect(self, midi):
        """건반 윗면의 평면 사각형."""
        whites, x0, _, kw, kh = self.piano._geometry()
        if _is_white(midi):
            return QRectF(x0 + whites.index(midi) * kw + 1, self._lane_h, kw - 2, kh - 1)
        x = black_x(x0 + whites.index(midi - 1) * kw + kw, kw, midi)
        return QRectF(x, self._lane_h, kw * BLACK_W, kh * BLACK_L)

    def _keys(self):
        whites = [m for m in range(MIDI_LOW, MIDI_HIGH + 1) if _is_white(m)]
        blacks = [m + 1 for m in whites if (m % 12) + 1 in BLACK_PCS and m + 1 <= MIDI_HIGH]
        return whites, blacks

    def _lip(self):
        return self.height() * LIP * self._scale

    def _faces(self, midi, pressed=False):
        """건반의 화면 면들 — (윗면, 앞면, [왼옆, 오른옆]). 흑건만 옆면이 있다.

        흑건 윗면은 흰 건반 면보다 BLACK_RISE만큼 위로, 눌리면 뒤쪽은 그대로·앞쪽만 DIP만큼 내려간다.
        """
        r = self._key_rect(midi)
        m = self._kxf.map
        bl, br, fr, fl = m(r.topLeft()), m(r.topRight()), m(r.bottomRight()), m(r.bottomLeft())
        lip = self._lip()
        rise = 0.0 if _is_white(midi) else lip * BLACK_RISE
        back = QPointF(0, -rise)
        front = QPointF(0, -rise + (lip * DIP if pressed else 0.0))
        tbl, tbr, tfr, tfl = bl + back, br + back, fr + front, fl + front
        top = QPolygonF([tbl, tbr, tfr, tfl])
        if _is_white(midi):           # 앞면 아래 끝은 고정 — 눌리면 앞면이 짧아진다
            return top, QPolygonF([tfl, tfr, fr + QPointF(0, lip), fl + QPointF(0, lip)]), []
        sides = [QPolygonF([bl, fl, tfl, tbl]), QPolygonF([br, fr, tfr, tbr])]
        return top, QPolygonF([tfl, tfr, fr, fl]), sides

    def _screen_rect(self, midi):
        """그 건반(앞면·빛기둥 포함)이 차지하는 화면 영역 — 부분 다시 그리기용."""
        r = self._key_rect(midi)
        beam = QRectF(r.left(), self._lane_h * (1 - BEAM), r.width(), self._lane_h * BEAM)
        area = self._kxf.mapRect(r).united(self._xf.mapRect(beam))
        lip = int(self._lip()) + 3
        return area.toAlignedRect().adjusted(-3, -lip, 3, lip)

    def keys_rect(self):
        """건반 전체(앞면 포함)의 화면 영역 — 첫 진입 가이드가 밝힐 자리."""
        whites, x0, _, kw, kh = self.piano._geometry()
        area = self._kxf.mapRect(QRectF(x0, self._lane_h, kw * len(whites), kh))
        return area.adjusted(0, 0, 0, self._lip()).toAlignedRect()

    def update_keys(self, midis):
        for midi in midis:
            if MIDI_LOW <= midi <= MIDI_HIGH:
                self.update(self._screen_rect(midi))

    # ── 색 규칙(PianoWidget 눌림 규칙 + 이미지 하이라이트) ────────
    def _pressed_color(self, midi):
        piano = self.piano
        if piano._is_out(midi):
            return QColor(T.KEY_PRESSED_OUT)
        return self._tone(midi) or QColor(T.TEXT_DIM)

    def _tone(self, midi):
        """음의 역할 색 — 지금 코드 근음 진함(스케일 밖이어도)·코드톤 중간·스케일음 연함, 그 외 None."""
        if midi % 12 == self.piano._chord_root:
            return QColor(TONE_ROOT)
        state = self.piano._content_state(midi)
        if state == "CHORD":
            return QColor(TONE_CHORD)
        return QColor(TONE_SCALE) if state == "SCALE" else None

    @staticmethod
    def _node_color(color):
        """리프 노드 색(BADGE_* 역할 표시) → 같은 파란 계열 진하기."""
        return QColor({T.BADGE_ROOT: TONE_ROOT, T.BADGE_CHORD: TONE_CHORD,
                       T.BADGE_SCALE: TONE_SCALE}.get(color, color))

    # ── 그리기 부품 ──────────────────────────────────────────────
    @staticmethod
    def _halo(p, poly, color):
        """화면 다각형 둘레에 같은 색 반투명 테두리 2겹 — 근음 형광 발광."""
        p.save()
        p.resetTransform()
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in ((12, 0.2), (6, 0.45)):
            c = QColor(color)
            c.setAlphaF(alpha * ROOT_GLOW / 0.45)
            pen = QPen(c, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPolygon(poly)
        p.restore()

    def _front(self, p, xf, rect, depth, color):
        """평면 사각형의 앞 모서리 아래로 두께 면을 화면 좌표에서 그린다(근음 색이면 발광)."""
        a = xf.map(rect.bottomLeft())
        b = xf.map(rect.bottomRight())
        self._fill(p, QPolygonF([a, b, b + QPointF(0, depth), a + QPointF(0, depth)]), color)

    def _fill(self, p, poly, brush, glow_root=True):
        """화면 다각형 채우기(근음 색이면 발광)."""
        if glow_root and isinstance(brush, QColor) and brush.name() == TONE_ROOT:
            self._halo(p, poly, brush)
        p.save()
        p.resetTransform()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(brush)
        p.drawPolygon(poly)
        p.restore()

    @staticmethod
    def _vgrad(poly, stops):
        """윗면 다각형의 뒤(0) → 앞(1) 방향 그라디언트."""
        a, b = (poly[0] + poly[1]) / 2, (poly[3] + poly[2]) / 2
        g = QLinearGradient(a, b)
        for t, c in stops:
            g.setColorAt(t, QColor(c))
        return g

    def _draw_white(self, p, midi, glow=None, pressed=False):
        if pressed:   # 내려앉으며 드러난 틈 = 이웃 건반의 옆벽(원래 윗면 자리를 옆벽 색으로 덮고 그 위에 그림)
            self._fill(p, self._faces(midi)[0], QColor("#7d8693"), glow_root=False)
        top, front, _ = self._faces(midi, pressed)
        base = glow if glow else QColor(T.KEY_W_FILL)
        # 뒤는 그늘, 앞은 밝게 — 눌리면 앞이 빛에서 멀어져 전체가 한 톤 어두워진다
        dark = 108 if pressed else 100
        stops = [(0, base.darker(118 + (dark - 100))), (0.25, base.darker(dark)),
                 (1, base.lighter(104) if not pressed else base.darker(dark + 4))]
        self._fill(p, top, self._vgrad(top, stops))
        p.save()
        p.resetTransform()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_hair(base.darker(150 if pressed else 125)))   # 이웃 건반과의 틈
        p.drawPolygon(top)
        p.restore()
        tone = glow.darker(125) if glow else (self._state_color(midi) or QColor("#a9b1bc"))
        fg = QLinearGradient(front[0], front[3])
        fg.setColorAt(0, tone.lighter(108))
        fg.setColorAt(1, tone.darker(125))
        if tone.name() == TONE_ROOT:
            self._halo(p, front, tone)
        self._fill(p, front, fg, glow_root=False)

    def _draw_black(self, p, midi, glow=None, pressed=False):
        top, front, sides = self._faces(midi, pressed)
        # 흰 건반 위 그림자(솟은 만큼 앞·옆으로 번짐, 눌리면 줄어듦)
        r = self._key_rect(midi)
        spread = r.width() * (0.10 if pressed else 0.18)
        shade = r.adjusted(-spread * 0.5, 0, spread, r.height() * (0.03 if pressed else 0.07))
        p.save()
        p.setTransform(self._kxf)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 55 if pressed else 85))
        p.drawRoundedRect(shade, 4, 4)
        p.restore()
        side = glow.darker(300) if glow else QColor("#07080b")
        for s in sides:
            self._fill(p, s, side, glow_root=False)
        tone = glow.darker(200) if glow else (self._state_color(midi) or QColor("#1b1e24"))
        if tone.name() == TONE_ROOT:
            self._halo(p, front, tone)
        fg = QLinearGradient(front[0], front[3])
        fg.setColorAt(0, tone.lighter(130))
        fg.setColorAt(1, tone.darker(140))
        self._fill(p, front, fg, glow_root=False)
        base = glow if glow else QColor("#2c3038")
        lo = 115 if pressed else 100
        stops = [(0, base.darker(190 + lo - 100)), (0.7, base.darker(lo + 15)),
                 (0.9, base.lighter(130) if not pressed else base.darker(lo)),   # 앞 모서리 광택
                 (1, base.darker(lo + 30))]
        self._fill(p, top, self._vgrad(top, stops), glow_root=False)
        p.save()
        p.resetTransform()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_hair(QColor(255, 255, 255, 18)))
        p.drawPolyline(QPolygonF([top[3], top[0], top[1]]))      # 윗면 테두리 반사광
        p.restore()

    def _state_color(self, midi):
        """현재 코드 스케일 표시 = 건반 앞면 색(파란 계열 진하기). 리프모드에선 없음."""
        return None if self.riff.show_notes else self._tone(midi)

    def _draw_walls(self, p):
        """도로 양옆에 서 있는 벽 — 평면 바닥선 위로 세운 패널을 원근으로."""
        w, lane = self.width(), self._lane_h
        steps = [0, .12, .3, .5, .72, 1.0]
        heights = [1.9, 1.3, 2.4, 1.6, 2.1]
        for side, x in ((-1, -0.12 * w), (1, 1.12 * w)):
            for i in range(len(steps) - 1):
                y0, y1 = steps[i] * lane, steps[i + 1] * lane
                f0, f1 = self._xf.map(QPointF(x, y0)), self._xf.map(QPointF(x, y1))
                s0 = self._xf.map(QPointF(x + side, y0)).x() - f0.x()
                s1 = self._xf.map(QPointF(x + side, y1)).x() - f1.x()
                hh = heights[i] * w * 0.25
                t0, t1 = f0 - QPointF(0, abs(s0) * hh), f1 - QPointF(0, abs(s1) * hh)
                p.setPen(QPen(QColor(T.BORDER_SUBTLE), 1))
                p.setBrush(QColor(WALL_TONES[i % len(WALL_TONES)]))
                p.drawPolygon(QPolygonF([f0, f1, t1, t0]))
                if i in (1, 3):    # 세로 네온 스트립 — 벽 아래쪽만(위쪽은 HUD 글자·버튼 자리)
                    mid0, mid1 = (f0 + f1) / 2, (t0 + t1) / 2
                    neon = QColor(TONE_SCALE if (i == 1) == (side < 0) else TONE_CHORD)
                    p.save()
                    p.setClipRect(QRectF(0, self.height() * 0.36, w, self.height()))   # HUD 아래만
                    p.setPen(QPen(neon, max(2.0, abs(s1) * w * 0.006)))
                    p.drawLine(mid0 - (mid0 - mid1) * .08, mid0 - (mid0 - mid1) * .3)
                    p.restore()

    def _build_cache(self):
        dpr = self.devicePixelRatioF()
        pix = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pix.setDevicePixelRatio(dpr)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, QColor("#0a101c"))
        bg.setColorAt(1, QColor(T.BG_BASE))
        p.fillRect(QRectF(0, 0, w, h), bg)
        self._draw_walls(p)
        p.setTransform(self._xf)
        road = QLinearGradient(0, 0, 0, self._lane_h)
        road.setColorAt(0, QColor("#0b1017"))
        road.setColorAt(1, QColor("#161e2a"))
        p.fillRect(QRectF(0, 0, w, self._lane_h), road)
        whites, x0, _, kw, _ = self.piano._geometry()
        p.setPen(_hair(QColor("#2a3444")))
        for i in range(1, len(whites)):
            x = x0 + i * kw
            p.drawLine(QPointF(x, 0), QPointF(x, self._lane_h))
        # 도로 양옆 레일(이미지의 밝은 테두리 띠): 바깥쪽에 폭 RAIL의 경사면
        rail = w * RAIL
        p.setPen(Qt.PenStyle.NoPen)
        for outer, inner in ((-rail, 0), (w + rail, w)):    # 도로 쪽이 밝게
            g = QLinearGradient(outer, 0, inner, 0)
            g.setColorAt(0, QColor("#2c3542"))
            g.setColorAt(1, QColor("#4b5667"))
            p.setBrush(g)
            x0r = min(outer, inner)
            p.drawRect(QRectF(x0r, 0, rail, self._lane_h))
        whites, blacks = self._keys()
        for midi in whites:
            self._draw_white(p, midi)
        for midi in blacks:
            self._draw_black(p, midi)
        p.end()
        self._cache = pix
        self.cache_builds += 1

    # ── 프레임 ───────────────────────────────────────────────────
    def paintEvent(self, event):
        piano = self.piano
        key = (self.width(), self.height(), frozenset(piano._note_set), frozenset(piano._chord_tones),
               tuple(sorted(piano._degrees.items())), piano._chord_root, self.riff.show_notes)
        if key != self._cache_key:
            self._build_cache()
            self._cache_key = key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._cache)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setTransform(self._xf)
        lane = QRectF(0, 0, self.width(), self._lane_h)
        glows = {m: self._pressed_color(m) for m in piano._pressed if MIDI_LOW <= m <= MIDI_HIGH}

        p.setClipRect(lane)
        p.setPen(_hair(QColor(255, 255, 255, 22)))
        for y in self.riff._beat_lines():
            p.drawLine(QPointF(0, y), QPointF(lane.width(), y))
        p.setPen(_hair(CHORD_LINE, 1.5))
        for y in self.riff._chord_lines():
            p.drawLine(QPointF(0, y), QPointF(lane.width(), y))
        sparkle = []                                    # (화면 다각형, 시드) — 근음 반짝이 자리
        for x, y, size, length, color in self.riff._nodes():
            c = self._node_color(color)
            if y + length >= self._lane_h - 1:          # 판정선 도착 = 그 건반 발광
                midi = piano._midi_at(x, 1)
                if midi is not None:
                    glows.setdefault(midi, c)
            trail = QLinearGradient(0, y, 0, y + length)
            fade = QColor(c)
            fade.setAlpha(0)
            trail.setColorAt(0, fade)
            fade.setAlpha(110)
            trail.setColorAt(1, fade)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(trail)
            p.drawRect(QRectF(x - size / 2, y, size, length))
            cap = QRectF(x - size / 2, y + length - min(length, size * 0.35), size, min(length, size * 0.35))
            p.setBrush(c.lighter(115))
            p.drawRoundedRect(cap, 4, 4)
            a, b = self._xf.map(cap.bottomLeft()), self._xf.map(cap.bottomRight())
            if c.name() == TONE_ROOT:                  # 근음 노드 발광
                self._halo(p, self._xf.map(QPolygonF(cap)), c)
                sparkle.append((self._xf.map(QPolygonF(cap)), round(x)))
            self._front(p, self._xf, cap, (b.x() - a.x()) * 0.12, c.darker(150))
        for midi, c in glows.items():                   # 건반에서 레인 위로 빛기둥
            r = self._key_rect(midi)
            beam = QRectF(r.left(), self._lane_h * (1 - BEAM), r.width(), self._lane_h * BEAM)
            g = QLinearGradient(0, beam.top(), 0, beam.bottom())
            fade = QColor(c)
            fade.setAlpha(0)
            g.setColorAt(0, fade)
            fade.setAlpha(120)
            g.setColorAt(1, fade)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawRect(beam)
        p.setClipping(False)

        whites, blacks = self._keys()
        pressed = piano._pressed
        # 다시 그릴 흰 건반 = 발광 + 눌리거나 발광한 흑건의 양옆(흑건이 내려앉은 자리 복원)
        lit_white = {m for m in whites if m in glows}
        lit_white |= {n for m in blacks if m in glows for n in (m - 1, m + 1)}
        for midi in whites:
            if midi in lit_white:
                self._draw_white(p, midi, glows.get(midi), midi in pressed)
        for midi in blacks:                             # 다시 그린 흰 건반 위로 흑건 복원
            if lit_white:
                self._draw_black(p, midi, glows.get(midi), midi in pressed)
        for midi in range(MIDI_LOW, MIDI_HIGH + 1):     # 근음 건반 앞면
            tone = self._state_color(midi)
            if tone is not None and tone.name() == TONE_ROOT:
                sparkle.append((self._faces(midi, midi in pressed)[1], midi))
        if not self.riff.show_notes:
            self._draw_numbers(p)
        self._draw_sparkles(p, sparkle)

    def _draw_numbers(self, p):
        """건반 윗면 앞쪽에 곡 스케일 번호. 지금 코드 근음은 진한 파란 원 안에 흰 숫자."""
        piano = self.piano
        if not piano._degrees:
            return
        p.resetTransform()
        for midi in range(MIDI_LOW, MIDI_HIGH + 1):
            number = piano._degrees.get(midi % 12)
            if not number:
                continue
            white = _is_white(midi)
            top = self._faces(midi, midi in piano._pressed)[0]   # 솟은·눌린 윗면 위에
            a, b = top[3], top[2]
            size = max(10.0, min(22.0, (b.x() - a.x()) * (0.42 if white else 0.5)))
            u = 0.8 if white else 0.72                           # 뒤(0) → 앞(1) 위치
            center = (top[0] + top[1]) / 2 * (1 - u) + (top[3] + top[2]) / 2 * u
            box = QRectF(center.x() - size, center.y() - size * 0.7, size * 2, size * 1.4)
            font = QFont(T.FONT_SANS_EN)
            font.setPixelSize(int(size * (0.62 if len(number) > 1 else 0.8)))
            font.setBold(number == "1" or midi % 12 == piano._chord_root)
            p.setFont(font)
            if midi % 12 == piano._chord_root:          # 근음 = 진한 파란 원 + 흰 숫자
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(TONE_ROOT))
                p.drawEllipse(center, size * 0.62, size * 0.62)
                p.setPen(QColor(T.WHITE))
            else:
                p.setPen(QColor("#1b2330" if white else "#e6ebf2"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, number)

    def _draw_sparkles(self, p, targets):
        """작은 4갈래 별빛이 제자리에서 각자 다른 박자로 깜빡인다(대부분 꺼져 있다 순간 반짝)."""
        p.resetTransform()
        now = time.monotonic()
        self._sparkle_areas = []
        for poly, seed in targets:
            box = poly.boundingRect()
            self._sparkle_areas.append(box.toAlignedRect().adjusted(-9, -9, 9, 9))
            rng = random.Random(seed)
            for _ in range(SPARKLE_COUNT):
                u, v, phase = rng.random(), rng.random(), rng.random()
                glint = max(0.0, math.sin(2 * math.pi * (SPARKLE_SPEED * now + phase))) ** 3
                if glint < 0.05:
                    continue
                c = QPointF(box.left() + box.width() * u, box.top() + box.height() * v)
                arm = 2 + 6 * glint
                halo = QColor(TONE_ROOT)
                halo.setAlphaF(0.6 * glint)
                core = QColor(255, 255, 255)
                core.setAlphaF(glint)
                for color, width in ((halo, 3.0), (core, 1.2)):
                    p.setPen(QPen(color, width, cap=Qt.PenCapStyle.RoundCap))
                    p.drawLine(c - QPointF(arm, 0), c + QPointF(arm, 0))
                    p.drawLine(c - QPointF(0, arm), c + QPointF(0, arm))
        if self._sparkle_areas and not self._sparkle_timer.isActive():
            self._sparkle_timer.start()
        elif not self._sparkle_areas:
            self._sparkle_timer.stop()

    # ── 마우스: 역변환 → 평평한 건반 좌표 ─────────────────────────
    def _midi_at(self, pos):
        pos = QPointF(pos)
        for midi in self._keys()[1]:                   # 솟은 흑건(윗면·앞면)이 화면에서 먼저
            top, front, _ = self._faces(midi)
            if (top.containsPoint(pos, Qt.FillRule.OddEvenFill)
                    or front.containsPoint(pos, Qt.FillRule.OddEvenFill)):
                return midi
        pt = self._kinv.map(pos)
        _, _, y0, _, kh = self.piano._geometry()
        y = pt.y() - self._lane_h
        if kh <= y <= kh * 1.15:                       # 앞면 두께 부분도 그 건반
            y = kh - 1
        return self.piano._midi_at(pt.x(), y + y0)

    def mousePressEvent(self, e):
        midi = self._midi_at(e.position())
        if midi is not None:
            self._mouse_midi = midi
            self.piano.notePlayed.emit(midi, True)

    def mouseReleaseEvent(self, e):
        if self._mouse_midi is not None:
            self.piano.notePlayed.emit(self._mouse_midi, False)
            self._mouse_midi = None
