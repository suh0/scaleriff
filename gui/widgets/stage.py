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
from PyQt6.QtGui import (QColor, QLinearGradient, QPainter, QPen, QPixmap,
                         QPolygonF, QTransform)
from PyQt6.QtWidgets import QWidget

from gui import theme as T
from gui.widgets.piano import BLACK_PCS, MIDI_HIGH, MIDI_LOW, PREVIEW_SPACE, WHITE_RATIO, _is_white

# 참고 이미지 실측(화면 비율): 레인 먼 끝 y≈0.13·폭≈0.18, 판정선 y≈0.64, 건반 앞 y≈0.93, 앞면 ≈0.033
TOP_Y = 0.13       # 레인 먼 끝의 화면 높이 비율
TOP_WIDTH = 0.34   # 레인 먼 끝의 폭(화면 폭 비율) = 시점 높이: 클수록 위에서 내려다본 원근(이미지는 0.18)
KEYS_TOP = 0.64    # 건반 윗선(판정선)의 화면 높이 비율
KEYS_BOTTOM = 0.925  # 건반 윗면 앞 모서리의 화면 높이 비율(그 아래 앞면 두께)
LIP = 0.033        # 흰 건반 앞면 두께(화면 높이 비율)
RAIL = 0.022       # 도로 양옆 레일 폭(평면 폭 비율)
BEAM = 0.45        # 빛기둥 길이(레인 길이 비율)

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
        x = x0 + whites.index(midi - 1) * kw + kw - kw * 0.3
        return QRectF(x, self._lane_h, kw * 0.6, kh * 0.62)

    def _keys(self):
        whites = [m for m in range(MIDI_LOW, MIDI_HIGH + 1) if _is_white(m)]
        blacks = [m + 1 for m in whites if (m % 12) + 1 in BLACK_PCS and m + 1 <= MIDI_HIGH]
        return whites, blacks

    def _lip(self):
        return self.height() * LIP * self._scale

    def _screen_rect(self, midi):
        """그 건반(앞면·빛기둥 포함)이 차지하는 화면 영역 — 부분 다시 그리기용."""
        r = self._key_rect(midi)
        beam = QRectF(r.left(), self._lane_h * (1 - BEAM), r.width(), self._lane_h * BEAM)
        area = self._kxf.mapRect(r).united(self._xf.mapRect(beam))
        return area.toAlignedRect().adjusted(-3, -3, 3, int(self._lip()) + 3)

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
        """현재 코드 기준 음의 역할 색 — 근음 진함·코드톤 중간·스케일음 연함, 그 외 None."""
        state = self.piano._content_state(midi)
        if state == "CHORD":
            return QColor(TONE_ROOT if self.piano._degrees.get(midi % 12) == "1" else TONE_CHORD)
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
        poly = QPolygonF([a, b, b + QPointF(0, depth), a + QPointF(0, depth)])
        if color.name() == TONE_ROOT:
            self._halo(p, poly, color)
        p.save()
        p.resetTransform()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(color)
        p.drawPolygon(poly)
        p.restore()

    def _draw_white(self, p, midi, glow=None):
        p.setTransform(self._kxf)
        r = self._key_rect(midi)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        top = glow.lighter(135) if glow else QColor("#dde2e8")
        g.setColorAt(0, top)
        g.setColorAt(1, glow if glow else QColor(T.KEY_W_FILL))
        p.setBrush(g)
        p.setPen(_hair(glow.darker(120) if glow else QColor(T.KEY_W_BORDER)))
        p.drawRoundedRect(r, 4, 4)
        front = glow.darker(125) if glow else (self._state_color(midi) or QColor("#c3c9d1").darker(125))
        self._front(p, self._kxf, r, self._lip(), front)

    def _draw_black(self, p, midi, glow=None):
        p.setTransform(self._kxf)
        r = self._key_rect(midi)
        shadow = QColor(0, 0, 0, 90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shadow)
        p.drawRoundedRect(r.translated(r.width() * 0.12, r.height() * 0.04), 4, 4)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0, glow.darker(160) if glow else QColor("#14171c"))
        g.setColorAt(1, glow if glow else QColor("#30353d"))
        p.setBrush(g)
        p.drawRoundedRect(r, 4, 4)
        front = glow.darker(200) if glow else (self._state_color(midi) or QColor("#30353d").darker(200))
        self._front(p, self._kxf, r, self._lip() * 0.6, front)

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
        bg.setColorAt(0, QColor("#0a0e15"))
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
        key = (self.width(), self.height(), frozenset(piano._note_set),
               frozenset(piano._chord_tones), tuple(sorted(piano._degrees.items())), self.riff.show_notes)
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
        if self.riff.show_notes:
            p.setPen(_hair(QColor(255, 255, 255, 22)))
            for y in self.riff._beat_lines():
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
        lit_white = [m for m in whites if m in glows]
        for midi in lit_white:
            self._draw_white(p, midi, glows[midi])
        for midi in blacks:                             # 발광한 흰 건반 위로 흑건 복원
            if midi in glows or lit_white:
                self._draw_black(p, midi, glows.get(midi))
        for midi in range(MIDI_LOW, MIDI_HIGH + 1):     # 근음 건반 앞면
            tone = self._state_color(midi)
            if tone is not None and tone.name() == TONE_ROOT:
                r = self._key_rect(midi)
                a, b = self._kxf.map(r.bottomLeft()), self._kxf.map(r.bottomRight())
                depth = self._lip() * (1 if _is_white(midi) else 0.6)
                sparkle.append((QPolygonF([a, b, b + QPointF(0, depth), a + QPointF(0, depth)]), midi))
        self._draw_sparkles(p, sparkle)

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
        pt = self._kinv.map(QPointF(pos))
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
