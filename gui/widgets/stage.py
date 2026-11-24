"""연주 무대 — 건반과 노드 레인을 원근(3D로 기울인 하이웨이)으로 그린다.

평면 좌표(world): 레인 y∈[0, lane_h], 건반 y∈[lane_h, lane_h+kh], x는 PianoWidget 좌표 그대로.
원근 변환 하나(평면 → 화면 사다리꼴, 참고 이미지 실측 비율)를 레인과 건반이 함께 쓴다:
건반 양옆이 레일 기울기 그대로 이어진다. 상수 = 화면 비율 그대로(이미지에서 잰 값을 바로 넣는다).

연주 중 비용: 벽·도로·레인 선은 배경 캐시(창 크기가 바뀔 때만), 눌리지 않은 건반·앞면 상태색은
코드 상태별 투명 건반 층 캐시(건반 영역만, 진입 첫 프레임에 곡의 모든 상태를 굽는다 — 코드 전환에 그리기 비용 없음).
무대는 불투명(WA_OpaquePaintEvent) — 매 프레임 밑의 창 공통 배경을 다시 그리지 않는다.
매 프레임: 배경 → 박자선 → 레인 직육면체(색 띠·노드) → 빛기둥 → 건반 층(맨 위, 눌림·발광 있으면 통째로 다시 그림).
건반 클릭은 역변환 한 번 → PianoWidget._midi_at, 다시 그리기는 바뀐 건반 영역만(update_keys).
"""
import functools
import math
import random
import time

from PyQt6.QtCore import Qt, QPointF, QRect, QRectF, QTimer
from PyQt6.QtGui import (QBrush, QColor,QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                         QPolygonF, QRadialGradient, QRegion, QTransform)
from PyQt6.QtWidgets import QWidget

from gui import theme as T
from gui.anim import reduced_motion
from gui.widgets.piano import (BLACK_L, BLACK_PCS, BLACK_W, MIDI_HIGH, MIDI_LOW, PREVIEW_SPACE,
                               WHITE_RATIO, _is_white, black_x)

# 화면 비율 그대로(축소 단계 없음). 먼 끝은 참고 이미지(1376×768) 실측, 건반은 예전 위치.
TOP_Y = 0.24       # 레인 먼 끝의 화면 높이 비율(배경 무대 바닥 뒤끝과 같은 높이)
TOP_WIDTH = 0.185  # 레인 먼 끝의 폭(화면 폭 비율)
KEYS_TOP = 0.681   # 건반 윗선(판정선)의 화면 높이 비율 — 건반은 예전 위치(이미지 0.62보다 아래, 레인이 길어짐)
HIT_WIDTH = 0.70   # 판정선에서 레인 폭(화면 폭 비율)
KEYS_BOTTOM = 0.864  # 건반 윗면 앞 모서리의 화면 높이 비율(그 아래 앞면 두께) — 앞 폭은 원근으로 ≈0.91
LIP = 0.042        # 흰 건반 앞면 두께(화면 높이 비율) — 건반 높이
BLACK_RISE = 0.65  # 흑건이 흰 건반 윗면보다 솟은 높이(흰 건반 앞면 두께 대비, 실측 12.7mm/≈20mm)
DIP = 0.42         # 눌림 깊이(흰 건반 앞면 두께 대비, 실측 10mm) — 뒤쪽 축 기준으로 앞이 내려감
BEAM = 0.45        # 빛기둥 길이(레인 길이 비율)
CHORD_LINE = QColor(255, 255, 255, 90)   # 코드 전환선(박자선보다 밝게)
CALL_DIM = QColor(0, 0, 0, 120)           # 리프 주고받기 중 프로그램 차례 마디 — 레인을 어둡게
SPLASH_LIFE = 0.45                       # 타격 스플래시·판정 문구 수명(초)

# 근음 파랑·코드톤 초록·스케일음 회색(앞면·노드·눌림 공통, 리프 노드 배지 색과 같음)
TONE_ROOT = T.BADGE_ROOT
TONE_CHORD = T.BADGE_CHORD
TONE_SCALE = T.BADGE_SCALE
BAND_ALPHA = {TONE_ROOT: 55, TONE_CHORD: 40, TONE_SCALE: 18}   # 자유연습 레일 색 띠(윗면) — 리프 노드보다 투명
NODE_ALPHA = 255        # 내 차례 리프 노드 = 불투명·선명
CALL_ALPHA = 110        # 프로그램 차례 리프 노드 윗면 불투명도(앞·옆면은 조금 더 진하게) — 칠 필요 없음
CALL_DARK = 180        # 프로그램 차례 노드 색 어둡게(QColor.darker 비율)
OUT_EDGE = "#8a94a3"    # 자유연습 스케일 밖 건반 = 투명, 이 색 테두리만
ROOT_GLOW = 0.8        # 근음 건반 발광(글로우) 세기 0~1
NOTE_GLOW = 1.5        # 내 차례 색 노드(근음·코드톤) 번짐 세기(겹 불투명도 배율)
# 번짐 겹(굵기 px, 불투명도). ponytail: 겹마다 굵은 외곽선 = 노드당 ~0.2ms(125%) — 4겹은 프레임 +3.6ms라 2겹
GLOW_LAYERS = ((16, 0.09), (7, 0.2))
SPARKLE_COUNT = 2       # 근음 건반·노드마다 별빛 개수(앞면 윗모서리 위)
SPARKLE_SPEED = 0.7     # 별빛이 밝아졌다 잦아드는 속도(Hz) — 느릴수록 자연스럽다
SPARKLE_SIZE = 7.0      # 별빛 가로 빛줄기 반길이(px)
SPARKLE_DOWN = 0.3      # 별빛 높이 = 앞면 윗변에서 아래로 이 비율
NEON_FADE = 0.55    # 네온 레일·점선이 먼 끝에서 투명 → 또렷해지는 구간(레인 길이 비율)
DASH_X = 0.044      # 흐르는 점선이 레일 바깥으로 떨어진 거리(평면 폭 비율, 참고 이미지 실측)
DASH_LEN = 0.016    # 점선 한 칸 길이(평면 폭 비율)
DASH_DEPTH = 0.004  # 점선 두께(레인 길이 비율)
DASH_PER_BEAT = 12  # 한 박에 점선 몇 칸
KEY_ROUND = 0.16    # 건반 모서리 둥글림 반지름(흰 건반 앞면 두께 대비)
NUMBER_STRETCH = 1.8  # 건반 번호 세로 배율(순수 원근이면 너무 납작해 읽기 어려움)
BAR_H = 0.1         # 재생바 받침 패널 높이(화면 높이 비율, 건반 아래 남은 높이로 제한)
# 아지랑이: 무대 배경과 도로 사이에 미리 구운 빛 안개 2겹을 위로 흘리며 숨 쉬듯 밝기만 바꾼다(픽셀 굴절 아님).
# ponytail: 안개 층 2장 덧그리기 = 1080p 약 3ms라 배경+안개를 HAZE_MS마다만 새로 굽는다(안개 한 걸음 ≈1px, 흐려서
# 계단 안 보임). 박 펄스 빛만 매 프레임. 재생 중엔 안개를 멈춤(굽기가 프레임을 튀게 함) — 재생 중에도 흐르게
# 하려면 GPU(QOpenGLWidget 셰이더)로.
HAZE_MS = 50            # 배경+안개 다시 굽는 주기 = 멈춤 중 다시 그리기 주기(재생 중엔 굽지 않음)
HAZE_LAYERS = ((T.NEON, 0.05, 6.0, 3), (T.ACCENT, 0.08, 8.5, 8))   # (색, 상승 속도 높이/초, 숨 주기 초, 시드)
HAZE_ALPHA = (110, 170)  # 안개 덩어리 하나의 진하기 범위(0~255)
PULSE_DECAY = 5.0       # 박 펄스가 잦아드는 빠르기(박 단위 지수 감쇠)


def _quad(rect, corners):
    """평면 사각형 → 화면 사각형(좌상·우상·우하·좌하) 원근 변환."""
    xf = QTransform()
    QTransform.quadToQuad(QPolygonF([rect.topLeft(), rect.topRight(), rect.bottomRight(), rect.bottomLeft()]),
                          QPolygonF([QPointF(x, y) for x, y in corners]), xf)
    return xf


@functools.lru_cache(maxsize=64)
def _glyphs(text, px, bold):
    """건반 번호 글자 외곽선(가운데 = 원점) — 원근 변환 아래 drawText는 매번 글자 경로를 새로 만들어 ~1ms."""
    font = QFont(T.FONTS)
    font.setPixelSize(px)
    font.setBold(bold)
    path = QPainterPath()
    path.addText(0, 0, font, text)
    return path.translated(-path.boundingRect().center())


def _len(v):
    return math.hypot(v.x(), v.y())


def _rounded(poly, radius):
    """화면 다각형 → 꼭짓점을 radius px만큼 살짝 둥글린 경로(짧은 변은 길이의 40%까지만).
    건반 면 좌표는 창 크기가 바뀔 때만 달라짐 → 좌표로 기억(건반 누를 때마다 다시 그리는 띠가 ~94개를 계산했음)."""
    return _rounded_at(tuple((q.x(), q.y()) for q in poly), radius)


@functools.lru_cache(maxsize=4096)
def _rounded_at(points, radius):
    poly = [QPointF(x, y) for x, y in points]
    path, n = QPainterPath(), len(poly)
    for i in range(n):
        a, v, b = poly[i - 1], poly[i], poly[(i + 1) % n]
        da, db = _len(a - v), _len(b - v)
        p1 = v + (a - v) * (min(radius, 0.4 * da) / da if da else 0)
        p2 = v + (b - v) * (min(radius, 0.4 * db) / db if db else 0)
        path.moveTo(p1) if i == 0 else path.lineTo(p1)
        path.quadTo(v, p2)
    path.closeSubpath()
    return path


def _hair(color, width=1.0):
    """원근 변환과 무관하게 화면에서 일정한 두께의 선."""
    pen = QPen(color, width)
    pen.setCosmetic(True)
    return pen


class Stage(QWidget):
    def __init__(self, piano, riff, parent=None):
        super().__init__(parent)
        self.gl = None                     # GL 무대(gui.widgets.gl_stage) — 붙으면 화면은 GL 창이 그린다
        self.hud_snap = None               # GL이 대신 그리는 HUD 창 그림(커튼 동안 HUD 창은 숨김)
        self.clock = None                  # 재생 중 () → (화면 시각, (박 위치, 마디당 박)) — GL이 그리는 순간 시각으로
        self.piano, self.riff = piano, riff
        piano.setParent(self)
        piano.hide()                       # 상태·기하 모델로만 사용
        riff.setParent(self)
        riff.hide()
        self.setMinimumHeight(240)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)   # 배경 그림이 무대 전체를 덮음
        self._states = []                  # 곡의 건반 상태들(set_states) — 캐시 한꺼번에 굽기
        self._xf = QTransform()            # 레인(평면 → 화면)
        self._kxf = QTransform()           # 건반(평면 → 화면)
        self._kinv = QTransform()
        self._lane_h = 1.0
        self._rects = {}                   # midi → 건반 평면 사각형
        self._bg = None                    # 배경 캐시(벽·도로·레일)
        self._haze = None                  # (안개 층 [(픽스맵, 상승, 숨 주기)], 소실점 펄스 빛, 반지름, 그릴 영역)
        self._hazed = None                 # (구운 시각, 배경+안개 픽스맵)
        self.beat = None                   # 재생 중 (박 위치, 마디당 박) — 박마다 펄스, 멈추면 None
        self._caches = {}                  # 건반 상태 → 배경+건반 캐시(오래 안 쓴 것부터 버림)
        self.cache_builds = 0              # 캐시 재생성 횟수(비용 측정용)
        self._mouse_midi = None
        # 근음 "샤랄라" 반짝이: 근음이 보일 때만 ~30fps로 그 영역만 다시 그림
        self._sparkle_areas = []
        self._splashes = []                # 리프 타격 (화면 점, 반지름, 시작 시각, 판정 문구)
        self._splash_areas = []
        # 재생 중(driven)엔 재생 틱이 매 프레임 전체를 그림 → 반짝이 타이머는 멈춘다(한 프레임 = 한 시각,
        # 부분 다시 그리기도 paintEvent 파이썬 비용은 전체와 같음)
        self.driven = False
        self._sparkle_timer = QTimer(self)
        self._sparkle_timer.setInterval(33)
        self._sparkle_timer.timeout.connect(
            lambda: [self.update(r) for r in self._sparkle_areas + self._splash_areas])
        self._haze_timer = QTimer(self)
        self._haze_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._haze_timer.setInterval(HAZE_MS)
        self._haze_timer.timeout.connect(lambda: self.driven or reduced_motion() or self.update())

    # ── 기하 ─────────────────────────────────────────────────────
    def resizeEvent(self, e):
        super().resizeEvent(e)
        w, h = self.width(), self.height()
        kw = w / 14
        self.piano.resize(w, int(kw * WHITE_RATIO) + PREVIEW_SPACE)
        _, _, _, _, kh = self.piano._geometry()
        far, near, hit = w * TOP_WIDTH / 2, w * HIT_WIDTH / 2, h * KEYS_TOP
        trap = [(w / 2 - far, h * TOP_Y), (w / 2 + far, h * TOP_Y), (w / 2 + near, hit), (w / 2 - near, hit)]
        # 레인 평면을 건반까지 연장했을 때 건반 앞 모서리가 KEYS_BOTTOM에 오도록 레인 길이를 정한다
        probe, _ = _quad(QRectF(0, 0, w, 1), trap).inverted()
        t = probe.map(QPointF(w / 2, h * KEYS_BOTTOM)).y()        # 레인 길이 1 기준 평면 깊이(>1)
        self._lane_h = kh / (t - 1)
        self.riff.resize(w, max(1, int(self._lane_h)))
        self._xf = self._kxf = _quad(QRectF(0, 0, w, self._lane_h), trap)
        self._kinv, _ = self._kxf.inverted()
        self._rects = {}
        self._bg = None
        self._haze = self._hazed = None
        self._caches.clear()
        if self.gl is not None:
            self.gl.resized()

    def _key_rect(self, midi):
        """건반 윗면의 평면 사각형(창 크기가 바뀔 때만 다시 계산 — 매 프레임 수십 번 불림)."""
        r = self._rects.get(midi)
        if r is None:
            whites, x0, _, kw, kh = self.piano._geometry()
            if _is_white(midi):
                r = QRectF(x0 + whites.index(midi) * kw + 1, self._lane_h, kw - 2, kh - 1)
            else:
                r = QRectF(black_x(x0 + whites.index(midi - 1) * kw + kw, kw, midi), self._lane_h,
                           kw * BLACK_W, kh * BLACK_L)
            self._rects[midi] = r
        return QRectF(r)

    def _keys(self):
        whites = [m for m in range(MIDI_LOW, MIDI_HIGH + 1) if _is_white(m)]
        blacks = [m + 1 for m in whites if (m % 12) + 1 in BLACK_PCS and m + 1 <= MIDI_HIGH]
        return whites, blacks

    def _lip(self):
        return self.height() * LIP

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
        area = self._key_box(midi).united(self._xf.mapRect(beam))   # 좌우: 흑건 그림자·발광 여유 포함
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


    # ── 그리기 부품 ──────────────────────────────────────────────
    @staticmethod
    def _halo(p, poly, color, strength=ROOT_GLOW):
        """화면 다각형 둘레 부드러운 번짐 — 굵기 다른 옅은 테두리를 겹쳐 가장자리에서 멀수록 옅어진다
        (가우시안 번짐 근사, 매 프레임 흐림 처리 없이). 안쪽 절반은 위에 칠하는 면이 덮는다."""
        p.save()
        p.resetTransform()
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width, alpha in GLOW_LAYERS:
            c = QColor(color)
            c.setAlphaF(alpha * strength)
            pen = QPen(c, width)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawPolygon(poly)
        p.restore()

    def _fill(self, p, poly, brush, glow_root=True):
        """화면 다각형 채우기(모서리 살짝 둥글게, 근음 색이면 발광)."""
        if glow_root and isinstance(brush, QColor) and brush.name() == TONE_ROOT:
            self._halo(p, poly, brush)
        p.save()
        p.resetTransform()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(brush)
        p.drawPath(_rounded(poly, self._lip() * KEY_ROUND))
        p.restore()

    def _edge_light(self, p, a, b, alpha):
        """둥근 모서리에 맺히는 가는 빛(윗면·앞면이 만나는 변 a→b)."""
        p.save()
        p.resetTransform()
        inset = (b - a) * (self._lip() * KEY_ROUND / max(1.0, _len(b - a)))
        p.setPen(_hair(QColor(255, 255, 255, alpha), 1.2))
        p.drawLine(a + inset, b - inset)
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
        if not glow and self._out_key(midi):          # 흑건처럼 상자 모서리 전부: 윗·앞면 + 두께만큼 내려간 양옆면
            down = QPointF(0, self._lip())
            sides = [QPolygonF([top[0], top[3], top[3] + down, top[0] + down]),
                     QPolygonF([top[1], top[2], top[2] + down, top[1] + down])]
            return self._outline(p, sides + [top, front])
        base = glow if glow else QColor(T.KEY_W_FILL)
        # 상아빛 윗면: 뒤(덮개 그늘) 어둡게 → 가운데 고른 흰색 → 앞 모서리 직전 광택 → 둥근 모서리로 살짝 넘어감.
        # 눌리면 앞이 빛에서 멀어져 전체가 한 톤 어두워진다
        d = 8 if pressed else 0
        stops = [(0, base.darker(150 + d)), (0.12, base.darker(112 + d)), (0.45, base.darker(103 + d)),
                 (0.86, base.darker(100 + d) if pressed else QColor(255, 255, 255)),
                 (0.95, base.darker(101 + d)), (1, base.darker(116 + d))]
        self._fill(p, top, self._vgrad(top, stops))
        p.save()
        p.resetTransform()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_hair(base.darker(160 if pressed else 135)))   # 이웃 건반과의 틈
        p.drawPath(_rounded(top, self._lip() * KEY_ROUND))
        p.restore()
        tone = glow.darker(125) if glow else (self._state_color(midi) or QColor("#d3d7dd"))
        fg = QLinearGradient(front[0], front[3])
        fg.setColorAt(0, tone.lighter(112))
        fg.setColorAt(0.25, tone)
        fg.setColorAt(1, tone.darker(135))
        if tone.name() == TONE_ROOT:
            self._halo(p, front, tone)
        self._fill(p, front, fg, glow_root=False)
        self._edge_light(p, front[0], front[1], 90 if pressed else 170)

    def _draw_black(self, p, midi, glow=None, pressed=False):
        top, front, sides = self._faces(midi, pressed)
        if not glow and self._out_key(midi):           # 투명 건반은 그림자도 없음
            return self._outline(p, sides + [top, front])
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
        base = glow if glow else QColor("#2a2d34")
        lo = 115 if pressed else 100
        # 광택 흑건: 뒤 짙은 검정 → 앞쪽 반사 띠(넓고 옅게 + 좁고 밝게) → 둥근 앞 모서리로 다시 어두워짐
        stops = [(0, base.darker(260 + lo - 100)), (0.5, base.darker(lo + 45)), (0.78, base.darker(lo + 5)),
                 (0.88, base.lighter(150) if not pressed else base.darker(lo)),
                 (0.94, base.darker(lo + 10)), (1, base.darker(lo + 60))]
        self._fill(p, top, self._vgrad(top, stops), glow_root=False)
        p.save()
        p.resetTransform()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_hair(QColor(255, 255, 255, 28)))
        p.drawPath(_rounded(top, self._lip() * KEY_ROUND))      # 윗면 테두리 반사광
        p.restore()
        self._edge_light(p, top[3], top[2], 40 if pressed else 85)

    def _state_color(self, midi):
        """현재 코드 스케일 표시 = 건반 앞면 색(파란 계열 진하기). 리프모드에선 없음."""
        return None if self.riff.show_notes else self._tone(midi)

    def _out_key(self, midi):
        """자유연습에서 치면 안 되는 스케일 밖 건반(지금 코드 근음 제외) — 투명 + 테두리만."""
        return not self.riff.show_notes and self.piano._is_out(midi)

    def _outline(self, p, faces):
        """투명 건반: 면은 비우고 모서리선만(입체감 유지)."""
        p.save()
        p.resetTransform()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(_hair(QColor(OUT_EDGE), 1.2))
        for poly in faces:
            p.drawPath(_rounded(poly, self._lip() * KEY_ROUND))
        p.restore()

    @staticmethod
    def _neon(p, a, b, alpha=255, fade=False):
        """화면 선분 a→b 네온(번진 빛 2겹 + 밝은 심). fade = a(먼 쪽)에서 투명 → NEON_FADE 지점부터 또렷."""
        for width, k, tone in ((14.0, 0.16, T.NEON), (6.0, 0.42, T.NEON), (2.2, 1.0, T.NEON_LIGHT)):
            g = QLinearGradient(a, b)
            c = QColor(tone)
            for t, f in (((0, 0.0), (NEON_FADE, 1.0), (1, 1.0)) if fade else ((0, 1.0), (1, 1.0))):
                c.setAlpha(int(alpha * k * f))
                g.setColorAt(t, c)
            pen = QPen(QBrush(g), width)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(a, b)

    def _draw_rails(self, p):
        """도로 양 끝 네온 레일선(정적, 배경 캐시) — 먼 끝에서 투명하게 소실."""
        p.save()
        p.resetTransform()
        for x in (0.0, self.width()):
            self._neon(p, self._xf.map(QPointF(x, 0)), self._xf.map(QPointF(x, self._lane_h)), fade=True)
        p.restore()

    def _draw_dashes(self, p):
        """레일 바깥 흐르는 점선(매 프레임) — 박자를 DASH_PER_BEAT로 나눈 시각에 평면 좌표로 놓아
        레인과 같은 원근·같은 속도로 내려온다. 박 위 점선은 밝게, 먼 끝은 투명."""
        w, lane = self.width(), self._lane_h
        gap, length, depth = w * DASH_X, w * DASH_LEN, lane * DASH_DEPTH
        p.setTransform(self._xf)
        p.setPen(Qt.PenStyle.NoPen)
        c = QColor(T.NEON_LIGHT)
        for y, on_beat in self.riff.dash_lines(DASH_PER_BEAT):
            c.setAlpha(int((230 if on_beat else 130) * min(1.0, 0.25 + y / lane)))   # 먼 끝도 옅게 보인다
            for x in (-gap - length, w + gap):
                p.fillRect(QRectF(x, y - depth, length, depth), c)

    def bar_rect(self):
        """재생바 자리 = 건반 아래 유리 패널 안쪽 육각형의 외접 사각형(화면). MainScreen이 재생바를 여기에 놓는다."""
        return self._bar_shape()[2]

    def _bar_shape(self):
        """건반 앞면 아래 받침 패널 — (바깥 사다리꼴, 안쪽 육각형, 안쪽 외접 사각형). 옆면은 45° 안쪽으로."""
        keys = self.keys_rect()
        top = keys.bottom() + 4
        h = max(30, min(self.height() * BAR_H, self.height() - top - 4))
        left, right = keys.left() - 4, keys.right() + 4
        outer = QPolygonF([QPointF(left, top), QPointF(right, top),
                           QPointF(right - h, top + h), QPointF(left + h, top + h)])
        pad = h * 0.12
        it, ib = top + pad, top + h - pad
        tip, cut = h * 1.35, (ib - it) / 2              # 안쪽 패널 양끝 = 꺾인 뾰족 끝
        mid = (it + ib) / 2
        inner = QPolygonF([QPointF(left + tip + cut, it), QPointF(right - tip - cut, it), QPointF(right - tip, mid),
                           QPointF(right - tip - cut, ib), QPointF(left + tip + cut, ib), QPointF(left + tip, mid)])
        return outer, inner, QRectF(left + tip, it, right - left - 2 * tip, ib - it).toAlignedRect()

    def _draw_bar_panel(self, p):
        """재생바 받침(정적, 배경 캐시): 반투명 유리 + 윗변 하이라이트 + 아랫변 네온."""
        outer, inner, _ = self._bar_shape()
        p.save()
        p.resetTransform()
        glass = QLinearGradient(0, outer[0].y(), 0, outer[2].y())
        glass.setColorAt(0, QColor(46, 44, 104, 170))
        glass.setColorAt(1, QColor(14, 14, 40, 215))
        p.setPen(_hair(QColor(T.NEON_LIGHT).darker(140), 1.0))
        p.setBrush(glass)
        p.drawPolygon(outer)
        p.setPen(_hair(QColor(139, 125, 255, 90)))
        p.setBrush(QColor(6, 8, 24, 200))
        p.drawPolygon(inner)
        self._neon(p, outer[3], outer[2], alpha=230)
        p.restore()

    def _build_bg(self):
        dpr = self.devicePixelRatioF()
        pix = QPixmap(int(self.width() * dpr) + 1, int(self.height() * dpr) + 1)   # +1: 불투명 무대 끝 픽셀까지(배율 125%)
        pix.setDevicePixelRatio(dpr)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        T.paint_backdrop(p, w, h, "stage_backdrop.webp")   # 연주 무대 전용 배경(빈 무대)
        vanish = self._xf.map(QPointF(w / 2, 0))       # 레인 먼 끝의 옅은 파란 빛 = 깊이감
        glow = QRadialGradient(vanish, w * 0.38)
        glow.setColorAt(0, QColor(91, 132, 255, 34))
        glow.setColorAt(1, QColor(91, 132, 255, 0))
        p.fillRect(QRectF(0, 0, w, h), glow)
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
        self._draw_rails(p)
        self._draw_bar_panel(p)
        p.end()
        return pix

    def _build_haze(self):
        """안개 층: 작은 그림에 세로로 긴 빛 덩어리를 위아래 이어지게(흘려도 이음매 없게) 그려 화면 크기로 키운다.
        가로는 흔들림 여유로 4% 넓게. 소실점 펄스 빛은 한 장만 구워 투명도로 맥동.
        그릴 영역 = 판정선 위에서 레인 사다리꼴을 뺀 곳(무대 벽·바닥) — 도로·건반은 안 덮고 칠할 픽셀도 줄어듦."""
        w, h, dpr = self.width(), self.height(), self.devicePixelRatioF()
        sw, sh = 192, 108
        layers = []
        for color, rise, period, seed in HAZE_LAYERS:
            small = QImage(sw, sh, QImage.Format.Format_ARGB32_Premultiplied)
            small.fill(Qt.GlobalColor.transparent)
            p = QPainter(small)
            rng = random.Random(seed)
            for _ in range(14):                         # 적고 진한 덩어리 = 흐르는 결이 보임(많으면 고르게 번짐)
                x, y, r = rng.uniform(0, sw), rng.uniform(0, sh), rng.uniform(6, 16)
                c = QColor(color)
                c.setAlpha(rng.randint(*HAZE_ALPHA))
                edge = QColor(c)
                edge.setAlpha(0)
                for dy in (-sh, 0, sh):                 # 위아래 이어 붙여도 끊기지 않게
                    cy = y + dy
                    g = QRadialGradient(QPointF(x, cy), r)
                    g.setColorAt(0, c)
                    g.setColorAt(1, edge)
                    p.save()                            # 세로로 늘인 타원 = 피어오르는 결
                    p.translate(x, cy)
                    p.scale(0.55, 1.6)
                    p.translate(-x, -cy)
                    p.fillRect(QRectF(x - r, cy - r, 2 * r, 2 * r), g)
                    p.restore()
            p.end()
            big = small.scaled(int(w * 1.04 * dpr) + 1, int(h * dpr) + 1, Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            pix = QPixmap.fromImage(big)
            pix.setDevicePixelRatio(dpr)
            layers.append((pix, rise, period))
        r = w * 0.22
        glow = QPixmap(int(2 * r * dpr) + 1, int(2 * r * dpr) + 1)
        glow.setDevicePixelRatio(dpr)
        glow.fill(Qt.GlobalColor.transparent)
        p = QPainter(glow)
        g = QRadialGradient(QPointF(r, r), r)
        for k in range(9):                              # 부드러운 감쇠(직선 감쇠는 가장자리 띠가 보임)
            u = k / 8
            g.setColorAt(u, QColor(139, 125, 255, int(110 * (1 - u * u) ** 2)))
        p.fillRect(QRectF(0, 0, 2 * r, 2 * r), g)
        p.end()
        lane = self._xf.map(QPolygonF(QRectF(0, 0, w, self._lane_h)))
        area = QRegion(0, 0, int(w) + 1, int(h * KEYS_TOP)) - QRegion(lane.toPolygon())
        return layers, glow, r, area

    def _pulse(self):
        """박 펄스 0~1: 박 머리에서 번쩍 → 지수로 잦아듦, 마디 첫 박은 더 세게."""
        if self.beat is None:
            return 0.0
        beat, per_bar = self.beat
        strong = 1.0 if math.floor(beat) % max(1, per_bar) == 0 else 0.5
        return strong * math.exp(-(beat % 1.0) * PULSE_DECAY)

    def _draw_back(self, p, region):
        """배경 + 아지랑이(배경과 합친 그림을 HAZE_MS마다 새로 구움) + 소실점 박 펄스(매 프레임).
        재생 중(driven)엔 안개를 멈춘다 — 굽기 ~8~10ms(1080p)가 3프레임에 1번 튀어 연주가 멈칫함(측정).
        스레드 굽기도 총 CPU가 같아 부하 있는 PC에선 평균이 안 줄었음. 박 펄스는 재생 중에도 매 프레임.
        건반만 다시 그릴 때(region이 아지랑이 자리 밖)는 굽지 않고 지난 그림을 쓴다."""
        if reduced_motion():
            p.drawPixmap(0, 0, self._bg)
            return
        if self._haze is None:
            self._haze = self._build_haze()
        layers, glow, r, area = self._haze
        t, w, h = time.perf_counter(), self.width(), self.height()
        if self._hazed is None or (not self.driven and t - self._hazed[0] >= HAZE_MS / 1000
                                   and region.intersects(area)):
            pix = QPixmap(self._bg)                     # 그리면 복사본으로 분리됨
            q = QPainter(pix)
            q.setClipRegion(area)
            q.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)   # 빛은 더해진다
            for i, (layer, rise, period) in enumerate(layers):
                off = (t * rise * h) % h                # 위로 흐름(두 장 이어 그려 빈틈 없음)
                breathe = 0.5 + 0.5 * math.sin(2 * math.pi * t / period + i * 2.1)
                sway = w * 0.02 * (math.sin(2 * math.pi * t / (period * 1.6) + i) - 1)   # 0 ~ -4% (층이 4% 넓음)
                q.setOpacity(0.35 + 0.45 * breathe)
                q.drawPixmap(QPointF(sway, -off), layer)
                q.drawPixmap(QPointF(sway, h - off), layer)
            q.end()
            self._hazed = (t, pix)
        p.drawPixmap(0, 0, self._hazed[1])
        p.save()
        p.setClipRegion(area)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        p.setOpacity(min(1.0, 0.25 + 0.75 * self._pulse()))
        p.drawPixmap(self._xf.map(QPointF(w / 2, 0)) - QPointF(r, r), glow)
        p.restore()

    def showEvent(self, e):
        super().showEvent(e)
        self._haze_timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._haze_timer.stop()

    def _build_cache(self):
        """지금 상태의 건반만 투명 층에 — 매 프레임 레인·노드 위에 덮는다. 건반 영역(_keys_area)만 잘라 보관
        (화면 전체의 ~1/4 — 곡의 모든 상태를 들고 있어도 1080p에서 상태당 ~2MB)."""
        dpr = self.devicePixelRatioF()
        pix = QPixmap(int(self.width() * dpr) + 1, int(self.height() * dpr) + 1)
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_keys(p)
        p.end()
        self.cache_builds += 1
        area = self._keys_area()                       # 실제 픽셀 경계로 잘라 제자리에 1:1로 다시 놓는다(배율 125%도)
        dev = QRect(int(area.x() * dpr), int(area.y() * dpr),
                    math.ceil(area.width() * dpr) + 1, math.ceil(area.height() * dpr) + 1)
        crop = pix.copy(dev)
        crop.setDevicePixelRatio(dpr)
        return QPointF(dev.x() / dpr, dev.y() / dpr), crop

    def set_states(self, states):
        """곡에 나오는 건반 상태 [(스케일 음, 강조음, 근음, 번호)] — 건반 캐시가 처음 빌 때(진입·창 크기 변경 뒤
        첫 프레임) 전부 한꺼번에 굽는다. 재생 중 코드 전환엔 건반 그리기가 없다."""
        self._states = list(states)
        self._caches.clear()                            # 이전 곡 상태는 버림(다음 프레임에 새 곡 전체를 굽는다)

    def prepare(self):
        """화면 진입 로딩 — 건반 층·배경을 지금 굽는다(커튼이 도는 중 첫 프레임에서 굽느라 끊기지 않게)."""
        if self._key_state() not in self._caches:
            self._build_caches()
        if self._bg is None:
            self._bg = self._build_bg()

    def _build_caches(self):
        """지금 상태 + 곡의 모든 상태 건반 층을 굽는다(이미 있는 것은 건너뜀). 피아노 상태는 원래대로 돌려 놓는다."""
        piano = self.piano
        saved = (piano._note_set, piano._chord_tones, piano._chord_root, piano._degrees)
        for state in [None, *self._states]:
            if state is not None:
                notes, tones, root, degrees = state
                piano.set_scale(notes, tones, root)
                piano.set_degrees(degrees)
            key = self._key_state()
            if key not in self._caches:
                self._caches[key] = self._build_cache()
        piano._note_set, piano._chord_tones, piano._chord_root, piano._degrees = saved

    def _draw_keys(self, p, glows=None, pressed=(), only=None):
        """건반: 흰 건반 → 흑건(그림자 포함), 건반마다 새긴 번호까지. only = 그릴 건반(없으면 전부).
        번호도 여기서 그려 건반 캐시에 함께 굽는다(원근 글자는 경로라 매 프레임 그리면 ~13ms)."""
        glows = glows or {}
        whites, blacks = self._keys()
        for midi in whites:
            if only is None or midi in only:
                self._draw_white(p, midi, glows.get(midi), midi in pressed)
                self._draw_number(p, midi, midi in pressed)
        for midi in blacks:
            if only is None or midi in only:
                self._draw_black(p, midi, glows.get(midi), midi in pressed)
                self._draw_number(p, midi, midi in pressed)

    def _key_box(self, midi):
        """건반 면들의 화면 영역 + 흑건 그림자·근음 발광 여유(폭의 1/4 + 8px). 창 크기가 바뀔 때만 계산."""
        box = self._rects.get(("box", midi))
        if box is None:
            top, front, _ = self._faces(midi)
            box = top.boundingRect().united(front.boundingRect())
            pad = box.width() * 0.25 + 8
            box = self._rects[("box", midi)] = box.adjusted(-pad, 0, pad, 0)
        return QRectF(box)

    def _keys_area(self):
        """건반 층이 차지하는 화면 영역(솟은 흑건·앞면·발광 여유 포함)."""
        lip = self._lip()
        return self.keys_rect().adjusted(-10, -int(lip * BLACK_RISE) - 10, 10, 10)

    def _unit(self, y):
        """깊이 y에서 평면 1px의 화면 폭 — 직육면체 높이를 원근에 맞춰 줄이는 비율(가로 축척은 깊이에만 의존)."""
        return self._xf.map(QPointF(1, y)).x() - self._xf.map(QPointF(0, y)).x()

    def _block(self, x, size, y0, y1, lift, k):
        """레인 직육면체의 보이는 면(옆, 윗, 앞) 화면 다각형. 평면 x±size/2 × 깊이 y0(먼)~y1(가까운),
        바닥 높이 lift(음수 = 도로 아래), 높이는 건반 두께(lip). 둘 다 판정선 기준 화면 px(k = 판정선 _unit)라
        깊이에 따라 원근 비율로 준다."""
        m = self._xf.map
        fl, fr = m(QPointF(x - size / 2, y0)), m(QPointF(x + size / 2, y0))   # 먼 쪽 바닥(lift 전)
        nl, nr = m(QPointF(x - size / 2, y1)), m(QPointF(x + size / 2, y1))   # 가까운 쪽 바닥
        uf, un = (fr.x() - fl.x()) / size / k, (nr.x() - nl.x()) / size / k   # 깊이별 높이 축척
        lip = self._lip()
        lo_f, hi_f = QPointF(0, lift * uf), QPointF(0, (lift + lip) * uf)
        lo_n, hi_n = QPointF(0, lift * un), QPointF(0, (lift + lip) * un)
        top = QPolygonF([fl - hi_f, fr - hi_f, nr - hi_n, nl - hi_n])
        front = QPolygonF([nl - hi_n, nr - hi_n, nr - lo_n, nl - lo_n])
        f, n = (fr, nr) if x < self.width() / 2 else (fl, nl)   # 가운데 쪽 옆면만 보인다
        side = QPolygonF([f - hi_f, n - hi_n, n - lo_n, f - lo_f])
        return side, top, front

    def _key_state(self):
        """건반 캐시 키 = 건반 그리기(_state_color·_out_key)가 읽는 것 전부. 리프모드 건반은 코드와 무관."""
        piano = self.piano
        if self.riff.show_notes:
            return (True,)
        return (False, frozenset(piano._note_set), frozenset(piano._chord_tones), piano._chord_root,
                frozenset(piano._degrees.items()))

    # ── 프레임 장면(CPU 그리기·GL 그리기 공통) ─────────────────────
    def _scene(self):
        """이번 프레임의 발광 건반 {midi: 색}과 레인 직육면체 [(x, size, y0, y1, lift, 색, 불투명도, 노드인지, 시드)].
        직육면체는 그릴 순서(먼 것·흰 건반·바깥 레인부터). 자유연습 코드 색 띠(반투명) + 리프 노드.
        윗면이 그 건반 윗면과 같은 높이(흑건 레인은 더 높게), 판정선·먼 끝은 평면 깊이로 자른다."""
        piano = self.piano
        glows = {m: self._pressed_color(m) for m in piano._pressed if MIDI_LOW <= m <= MIDI_HIGH}
        kw, rise = piano._geometry()[3], self._lip() * BLACK_RISE
        sources = [(b, BAND_ALPHA[b[4]], False) for b in self.riff.chord_bands()]
        for *node, call in self.riff._nodes():
            x, y, _, length, color = node
            if call:                                    # 프로그램 차례 = 어둡고 투명하게, 발광 없음(칠 필요 없음)
                node[4] = QColor(color).darker(CALL_DARK).name()
                sources.append((node, CALL_ALPHA, False))
                continue
            if y + length >= self._lane_h - 1:          # 판정선 도착 = 그 건반 발광
                midi = piano._midi_at(x, 1)
                if midi is not None:
                    glows.setdefault(midi, QColor(color))
            sources.append((node, NODE_ALPHA, True))
        blocks = []
        for (x, y, size, length, color), alpha, solid in sources:
            y0, y1 = max(0.0, y), min(self._lane_h, y + length)
            if y0 < y1:
                # 윗면 = 그 건반 윗면 높이(흰 0·흑 rise), 아래로 건반 두께만큼. 흰 건반 레인 폭 = 격자 한 칸
                lift = (0.0 if size >= kw - 1e-6 else rise) - self._lip()
                blocks.append(((y1, lift, -abs(x - self.width() / 2)),
                               (x, size, y0, y1, lift, color, alpha, solid, round(x))))
        return glows, [b for _, b in sorted(blocks, key=lambda b: b[0])]

    def _strips(self, glows):
        """눌림·발광 건반이 지나는 세로 띠(건반 층 높이) 영역과 그 안에서 다시 그릴 건반들."""
        area = self._keys_area()
        strips = QRegion()
        for midi in glows:
            box = self._key_box(midi)
            strips |= QRegion(QRect(int(box.left()), area.top(), int(box.width()) + 2, area.height()))
        return strips, {m for m in range(MIDI_LOW, MIDI_HIGH + 1)
                        if strips.intersects(self._key_box(m).toAlignedRect())}

    def _root_fronts(self):
        """지금 코드 근음 건반들의 앞면(별빛 자리) [(화면 다각형, 시드)]."""
        pressed = self.piano._pressed
        out = []
        for midi in range(MIDI_LOW, MIDI_HIGH + 1):
            tone = self._state_color(midi)
            if tone is not None and tone.name() == TONE_ROOT:
                out.append((self._faces(midi, midi in pressed)[1], midi))
        return out

    # ── 프레임 ───────────────────────────────────────────────────
    def update(self, *args):
        """GL 무대가 붙어 있으면 다시 그리기는 GL 창이(무대 위젯 자체는 그리지 않음)."""
        if self.gl is not None:
            self.gl.update()
        else:
            super().update(*args)

    def paintEvent(self, event):
        if self.gl is not None:                         # 화면에는 GL 창이 덮여 있다
            return
        piano = self.piano
        key = self._key_state()
        if key not in self._caches:                     # 진입·창 크기 변경 뒤 첫 프레임 = 곡 전체 로딩
            self._build_caches()
        cache = self._caches[key]
        if self._bg is None:
            self._bg = self._build_bg()
        p = QPainter(self)
        self._draw_back(p, event.region())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setTransform(self._xf)
        lane = QRectF(0, 0, self.width(), self._lane_h)
        glows, scene = self._scene()

        for top, bottom in self.riff.call_bands():      # 프로그램 차례 마디 = 도로 어둡게
            p.fillRect(QRectF(0, top, self.width(), bottom - top), CALL_DIM)
        p.setClipRect(lane)
        chord_lines = self.riff._lines(self.riff._chord_grid) if self.riff._chord_grid else []
        for lines, white, width in ((self.riff._lines(), QColor(255, 255, 255, 22), 1.0),
                                    (chord_lines, CHORD_LINE, 1.5)):
            orange = QColor(T.DETOUR)                   # 키 밖 코드 구간 = 같은 밝기의 옅은 주황
            orange.setAlpha(white.alpha())
            for y, when in lines:
                p.setPen(_hair(orange if self.riff.in_detour(when) else white, width))
                p.drawLine(QPointF(0, y), QPointF(lane.width(), y))
        p.setClipping(False)
        self._draw_dashes(p)
        k = self._unit(self._lane_h)
        sparkle = []                                    # (화면 다각형, 시드) — 근음 반짝이 자리
        p.resetTransform()
        p.setPen(Qt.PenStyle.NoPen)
        for x, size, y0, y1, lift, color, alpha, solid, seed in scene:
            side, top, front = self._block(x, size, y0, y1, lift, k)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, solid)   # 반투명 띠는 계단 안 보임 — 비용 절반
            c = QColor(color)
            if solid and color != TONE_SCALE:          # 색 노드 = 같은 색으로 은은히 번짐
                self._halo(p, QPolygonF([top[0], top[1], front[2], front[3]]), c, NOTE_GLOW)
            if solid and color == TONE_ROOT:
                sparkle.append((front, seed))
            # 노드: 윗면 = 제 색 그대로·앞면 살짝 진하게(유리판 느낌), 반투명 띠는 예전 음영
            if solid:
                shades = ((side, c.darker(170)), (top, QColor(c)), (front, c.darker(115)))
            else:
                shades = ((side, c.darker(170)), (top, QColor(c)), (front, c.darker(140)))
            for (poly, f), k in zip(shades, (1.3, 1.0, 1.5)):
                f.setAlpha(min(255, int(alpha * k)))
                p.setBrush(f)
                p.drawPolygon(poly)
            if solid:                                   # 밝은 모서리(윗면 둘레·앞면 테두리)
                p.setBrush(Qt.BrushStyle.NoBrush)
                rim = c.lighter(175)
                for poly, a in ((top, 220), (front, 120)):
                    rim.setAlpha(a)
                    p.setPen(_hair(rim))
                    p.drawPolygon(poly)
                p.setPen(Qt.PenStyle.NoPen)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setTransform(self._xf)
        p.setClipRect(lane)
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

        # 건반은 맨 위 — 레인·노드가 가리지 않는다. 눌림·발광 건반이 지나는 세로 띠만 처음부터 다시 그리고
        # (띠 안 흰 건반 → 흑건·그림자, 그림자가 한 번만 얹힘) 나머지는 캐시. 두 쪽 모두 같은 기하라 경계에 이음매 없음.
        p.resetTransform()
        strips, only = self._strips(glows)
        p.save()
        p.setClipRegion(QRegion(self._keys_area()) - strips)
        p.drawPixmap(*cache)
        if glows:
            p.setClipRegion(strips)
            self._draw_keys(p, glows, piano._pressed, only)
        p.restore()
        self._draw_splashes(p)
        self._draw_sparkles(p, sparkle + self._root_fronts())

    def splash(self, label, x):
        """리프 노드를 맞힌 자리(판정선)에 스플래시 + 판정 문구."""
        kw = self.piano._geometry()[3]
        a, b = self._xf.map(QPointF(x - kw / 2, self._lane_h)), self._xf.map(QPointF(x + kw / 2, self._lane_h))
        radius = max(14.0, (b.x() - a.x()) * 0.6)
        self._splashes.append(((a + b) / 2, radius, time.perf_counter(), label))
        self._splash_areas.append(self._splash_rect((a + b) / 2, radius))
        self.update(self._splash_areas[-1])
        if not self._sparkle_timer.isActive() and not self.driven:
            self._sparkle_timer.start()

    @staticmethod
    def _splash_rect(c, radius):
        r = int(max(radius * 1.7, 44))
        return QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r).toAlignedRect()

    def _live_splashes(self):
        """수명 남은 스플래시만 남기고 그 화면 영역들(지금 시각 기준)."""
        now = time.perf_counter()        # monotonic은 Windows에서 15.6ms 계단 → 60fps 애니메이션이 뭉침
        self._splashes = [s for s in self._splashes if now - s[2] < SPLASH_LIFE]
        self._splash_areas = [self._splash_rect(c, r) for c, r, _, _ in self._splashes]
        return self._splash_areas

    def _draw_splashes(self, p, origin=QPointF()):
        """커지며 옅어지는 링 + 튀는 점 6개 + 가운데 작은 판정 문구. origin = 그림의 화면 원점(GL은 작은 그림에)."""
        p.setTransform(QTransform.fromTranslate(-origin.x(), -origin.y()))
        self._live_splashes()
        now = time.perf_counter()
        font = QFont(T.FONTS)
        font.setPixelSize(12)
        font.setBold(True)
        p.setFont(font)
        for c, radius, start, label in self._splashes:
            u = (now - start) / SPLASH_LIFE
            color = QColor(TONE_ROOT).lighter(170) if label == "PERFECT" else QColor(255, 255, 255)
            color.setAlphaF(1 - u)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(color, 3 * (1 - u) + 0.5))
            p.drawEllipse(c, radius * (0.4 + 0.8 * u), radius * (0.4 + 0.8 * u) * 0.45)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            for k in range(6):
                angle = math.pi * (k / 3 + 1 / 6)
                d = radius * (0.3 + 1.1 * u)
                p.drawEllipse(c + QPointF(math.cos(angle) * d, math.sin(angle) * d * 0.45 - 6 * u), 2.5 * (1 - u), 2.5 * (1 - u))
            text = QColor(color)
            text.setAlphaF(min(1.0, 2.5 * (1 - u)))
            p.setPen(text)
            p.drawText(QRectF(c.x() - 40, c.y() - radius * 0.7 - 10 - 8 * u, 80, 20), Qt.AlignmentFlag.AlignCenter, label)

    def _draw_number(self, p, midi, pressed):
        """건반 윗면 앞쪽에 곡 스케일 번호를 파서 새긴 것처럼(자유연습만) — 윗면 원근에 맞춰 눕히고(평면 → 윗면
        사각형 변환), 파인 홈의 윗벽 그늘·아랫벽 빛을 1px 어긋나게 겹친다. 지금 코드 근음은 박아 넣은 파란 원 + 흰 숫자."""
        piano = self.piano
        number = None if self.riff.show_notes else piano._degrees.get(midi % 12)
        if number:
            white = _is_white(midi)
            top = self._faces(midi, pressed)[0]          # 솟은·눌린 윗면 위에
            r = self._key_rect(midi)
            w, h = r.width(), r.height()
            flat = QTransform()
            if not QTransform.quadToQuad(QPolygonF([QPointF(0, 0), QPointF(w, 0), QPointF(w, h), QPointF(0, h)]),
                                         top, flat):
                return
            size = w * (0.36 if white else 0.5)                  # 건반 평면 단위(화면에선 원근으로 눕는다)
            c = QPointF(w / 2, h * (0.84 if white else 0.8))     # 뒤(0) → 앞(h) 위치
            # 원근만 따르면 글자가 납작해 읽기 어렵다 → 세로만 STRETCH배(그래도 건반에 누운 모양 유지)
            flat = QTransform().translate(c.x(), c.y()).scale(1, NUMBER_STRETCH) * flat
            root = midi % 12 == piano._chord_root
            glyphs = _glyphs(number, max(1, int(size * (0.78 if len(number) > 1 else 1.0))), number == "1" or root)
            p.setPen(Qt.PenStyle.NoPen)
            if root:                                    # 박아 넣은 파란 원(위 가장자리 그늘)
                p.setTransform(flat)
                p.setBrush(QColor(TONE_ROOT).darker(170))
                p.drawEllipse(QPointF(0, 0), size * 0.68, size * 0.68)
                p.setTransform(flat * QTransform.fromTranslate(0, 1.2))
                p.setBrush(QColor(TONE_ROOT))
                p.drawEllipse(QPointF(0, 0), size * 0.68, size * 0.68)
                layers = ((QColor(0, 0, 0, 110), -0.9), (QColor(T.WHITE), 0))
            elif white:                                 # 상아에 판 홈: 윗벽 그늘 · 아랫벽 빛 · 홈 바닥
                layers = ((QColor(255, 255, 255, 235), 1.1), (QColor(20, 26, 36, 150), -0.8),
                          (QColor("#4a525e"), 0))
            else:                                       # 흑건에 판 홈(은빛으로 메움)
                layers = ((QColor(0, 0, 0, 220), -1.0), (QColor(255, 255, 255, 60), 1.0),
                          (QColor("#b9c0cb"), 0))
            for color, dy in layers:
                p.setTransform(flat * QTransform.fromTranslate(0, dy))
                p.setBrush(color)
                p.drawPath(glyphs)
        p.resetTransform()

    def _sparkle_stars(self, targets):
        """근음 별빛 [(중심, 크기, 밝기)]: 앞면 윗모서리(빛이 맺히는 곳) 위 제자리에서 서서히 밝아졌다 잦아든다
        (완전히 꺼지지 않음). 멈춤 중 반짝이 타이머도 여기서 켜고 끈다."""
        now = time.perf_counter()
        self._sparkle_areas = []
        stars = []
        for poly, seed in targets:
            tl, tr, br, bl = poly[0], poly[1], poly[2], poly[3]   # 앞면(윗변 왼·오, 아랫변 오·왼)
            rng = random.Random(seed)
            for i in range(SPARKLE_COUNT):             # 별빛마다 제 구간(겹쳐 붙지 않게)
                u, phase = (i + 0.2 + 0.6 * rng.random()) / SPARKLE_COUNT, rng.random()
                tw = (0.5 + 0.5 * math.sin(2 * math.pi * (SPARKLE_SPEED * now + phase))) ** 2
                top, low = tl + (tr - tl) * u, bl + (br - bl) * u
                c = top + (low - top) * SPARKLE_DOWN           # 윗모서리 바로 안쪽(흰 건반 윗면에 묻히지 않게)
                size = SPARKLE_SIZE * (0.65 + 0.35 * tw)
                stars.append((c, size, 0.2 + 0.8 * tw))
                r = int(size) + 4
                self._sparkle_areas.append(QRect(int(c.x()) - r, int(c.y()) - r, 2 * r, 2 * r))
        if (self._sparkle_areas or self._splash_areas) and not self.driven:
            if not self._sparkle_timer.isActive():
                self._sparkle_timer.start()
        else:
            self._sparkle_timer.stop()
        return stars

    def _draw_sparkles(self, p, targets):
        p.resetTransform()
        p.setPen(Qt.PenStyle.NoPen)
        for c, size, alpha in self._sparkle_stars(targets):
            self._star(p, c, size, alpha)

    @staticmethod
    def _star(p, c, size, alpha):
        """4갈래 별빛 — 끝으로 갈수록 가늘어지는 빛줄기(가로가 더 길다) + 가운데 둥근 빛."""
        glow = QRadialGradient(c, size * 0.55)
        glow.setColorAt(0, QColor(255, 255, 255, int(170 * alpha)))
        glow.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(glow)
        p.drawEllipse(c, size * 0.55, size * 0.55)
        w, v = max(0.7, size * 0.1), size * 0.6
        p.setBrush(QColor(255, 255, 255, int(255 * alpha)))
        p.drawPolygon(QPolygonF([c - QPointF(size, 0), c - QPointF(0, w), c + QPointF(size, 0), c + QPointF(0, w)]))
        p.drawPolygon(QPolygonF([c - QPointF(0, v), c + QPointF(w, 0), c + QPointF(0, v), c - QPointF(w, 0)]))

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
