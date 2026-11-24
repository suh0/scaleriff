"""화면 전환 = 커튼: 양옆에서 커튼이 나와 무대를 가리고(가운데서 만나며 살짝 튕김) 다시 양옆으로 걷힌다.
천(주름·조명)과 움직임(레일 곡선·밑단 스프링)은 코드로 그린다 — 이미지 시퀀스 없이 창 크기·주사율과 무관."""
from __future__ import annotations

import math
import time
from functools import lru_cache

import numpy as np
from PyQt6.QtCore import QEasingCurve, QPoint, QRect, QRectF, QSettings, Qt, QVariantAnimation
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QStackedWidget, QWidget

CLOSE_MS = 460      # 양옆에서 나와 가운데서 만나기까지(튕김 포함)
HOLD_MS = 180       # 닫힌 채 머무는 시간(밑단 흔들림이 잦아들어 일자로 서는 순간)
OPEN_MS = 850       # 걷히는 시간
MEET = 0.6          # 닫힘 중 가운데서 만나는 시점(비율) — 이후는 튕김
CLOSED = 1.04       # 닫혔을 때 레일 위치(반폭 비율) — 두 폭이 가운데서 겹쳐 튕겨도 틈이 안 생김
BOUNCE = 0.07       # 튕김 세기(반폭 비율, 첫 반동 ≈ 3%)
GATHER = 0.1        # 다 걷혔을 때 남는 폭(반폭 비율) — 이후 옅어지며 사라짐
HEM_K, HEM_C = 700.0, 28.0   # 밑단 스프링(강성·감쇠, 초 단위) — 레일을 늦게 따라가다 멈추면 한 번 흔들리고 곧 선다
STRIPS = 148        # 천을 그리는 가로 띠 수(띠마다 안쪽 가장자리가 다름 → 굽은 가장자리)
CURTAIN_FOLDS = 8   # 커튼 한 폭의 주름 수
CURTAIN_DARK, CURTAIN_LIGHT = QColor("#10153a"), QColor("#2b3584")   # 남색 벨벳(앱 남색 배경 톤)
CAST = 36           # 커튼 안쪽 가장자리 그늘 폭

_leaving = None     # (떠나는 화면 그림, 그 화면 좌상단 전역 좌표) — 다음 커튼이 그 위로 닫힌다


def reduced_motion() -> bool:
    app = QApplication.instance()
    return bool(app and app.property("reduceMotion"))


def set_reduced_motion(on: bool):
    app = QApplication.instance()
    if app:
        app.setProperty("reduceMotion", bool(on))
    QSettings("graduation-project", "ScaleRiff").setValue("reduce_motion", bool(on))


def _closing(s):
    """닫힘 레일 위치(0=양끝, CLOSED=가운데서 겹침): 끌려오며 빨라져 가운데서 부딪고 두 번 작게 튕긴다."""
    if s < MEET:
        return CLOSED * (s / MEET) ** 1.3
    t = (s - MEET) / (1 - MEET)
    return CLOSED - BOUNCE * math.exp(-3 * t) * abs(math.sin(2 * math.pi * t))


@lru_cache(maxsize=4)                       # 창 크기마다 한 번만 굽는다(전환마다 다시 굽지 않음)
def _fabric(w, h, dpr, left):
    """커튼 한 폭 천(무광 벨벳)을 실제 화면 픽셀로 굽는다 — 곧은 수직 주름 표면에 바깥 위에서 빛을 비춰(확산광만,
    광택 없음) 골은 어둡게, 레일 아래 주름 머리 그늘, 고운 벨벳 결, 위 조명·아래 그늘·밑단."""
    pw, ph = math.ceil(w * dpr), math.ceil(h * dpr)
    f32 = np.float32
    x = np.linspace(0, 1, pw, dtype=f32)[None, :]                # 0 = 바깥(화면 끝), 1 = 안쪽(무대 가운데)
    y = np.linspace(0, 1, (ph + 3) // 4, dtype=f32)[:, None]     # 주름 모양은 세로로 천천히 변함 → 4줄마다 계산
    phase = (2 * np.pi * CURTAIN_FOLDS * x + 1.1 * np.sin(2 * np.pi * 1.7 * x)      # 주름은 곧게 수직(닫혀 멈추면 일자)
             + 0.5 * np.sin(2 * np.pi * 3.1 * x + 1))
    depth = 0.7 + 0.3 * np.sin(2 * np.pi * (1.3 * x + 0.2 * y) + 0.5)  # 주름마다 깊이가 다름
    slope = -2.0 * depth * np.sin(phase)                         # 주름 표면 기울기
    lit = ((-slope * -0.5 + 0.866) / np.sqrt(slope ** 2 + 1) + 0.3) / 1.3   # 바깥 위 빛, 부드러운 확산(무광)
    v = np.clip(lit, 0, 1) * (1 - 0.6 * (0.5 - 0.5 * np.cos(phase)) * depth) * (0.82 + 0.18 * x)
    v = np.repeat(v, 4, axis=0)[:ph]
    rng = np.random.default_rng(7)                               # 벨벳 결(세로 올 + 고운 입자) — 매번 같은 천
    v *= 1 + rng.normal(0, 0.018, (1, pw)).astype(f32)
    v += rng.normal(0, 0.006, (ph, pw)).astype(f32)
    ys = np.linspace(0, h, ph, dtype=f32)[:, None]               # 논리 px
    vert = (1.04 - 0.5 * (ys / h) ** 1.5) * (1 - 0.45 * np.exp(-ys / 9))   # 위 조명 → 아래 그늘, 레일 아래 그늘
    vert[ys[:, 0] > h - 16] *= 0.72                              # 밑단: 접어 박은 단(그늘 + 살짝 밑은 접힘선)
    vert[np.abs(ys[:, 0] - (h - 16)) < 0.8] *= 1.35
    dark = np.array(CURTAIN_DARK.getRgbF()[:3], f32) * 255
    light = np.array(CURTAIN_LIGHT.getRgbF()[:3], f32) * 255
    np.clip(v, 0, 1, out=v)
    a = np.empty((ph, pw, 4), np.uint8)
    for ch in range(3):
        a[..., ch] = np.clip((dark[ch] + (light[ch] - dark[ch]) * v) * vert + 0.5, 0, 255)
    a[..., 3] = 255
    if not left:                                                 # 오른쪽 폭 = 거울상
        a = np.ascontiguousarray(a[:, ::-1])
    pix = QPixmap.fromImage(QImage(a.data, pw, ph, pw * 4, QImage.Format.Format_RGBA8888).copy())
    pix.setDevicePixelRatio(dpr)
    return pix


@lru_cache(maxsize=2)
def _cast(left):
    """안쪽 가장자리 그늘(CAST×1) — 띠마다 굽은 가장자리에 맞춰 늘려 그린다."""
    img = QPixmap(CAST, 1)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    g = QLinearGradient(CAST if left else 0, 0, 0 if left else CAST, 0)
    g.setColorAt(0, QColor(0, 0, 0, 130))
    g.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(QRectF(0, 0, CAST, 1), g)
    p.end()
    return img


class _Under(QWidget):
    """닫히는 동안 커튼 밑에 깔리는 떠난 화면 그림(새 화면은 커튼이 닫힌 뒤에야 보임)."""

    def __init__(self, parent, pix, origin):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pix, self._origin = pix, origin

    def resizeEvent(self, e):                                  # 그림이 다 덮을 때만 밑 화면을 안 그림
        rect = QRect(self.mapFromGlobal(self._origin), self._pix.deviceIndependentSize().toSize())
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, rect.contains(self.rect()))

    def paintEvent(self, e):
        QPainter(self).drawPixmap(self.mapFromGlobal(self._origin), self._pix)


class _Cloth(QWidget):
    """커튼 한 폭의 일부 — 몸통(불투명, 밑 화면 안 그림)이나 굽은 가장자리 띠. 폭 전체를 커튼 좌표로 그리고
    제 영역만 남는다(위젯 밖은 잘림). 천은 띠마다 안쪽 가장자리에 맞춰 늘어나 주름도 함께 휜다(걷히면 모임)."""

    def __init__(self, curtain, left, body):
        super().__init__(curtain)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._c, self._left, self._body = curtain, left, body

    def paintEvent(self, e):
        c = self._c
        p = QPainter(self)
        p.setOpacity(c.alpha)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)   # 늘리고 줄일 때 픽셀이 뭉개지지 않게
        p.setRenderHint(QPainter.RenderHint.Antialiasing)            # 굽은 가장자리 1px 계단 없이(띠 위아래는 픽셀 줄에 맞음)
        p.translate(-self.x(), 0)
        pix, cast = c.fabric(self._left), c.cast[0 if self._left else 1]
        w, h = c.width(), c.height()
        pw, dpr = pix.width(), pix.devicePixelRatio()
        rows = pix.height()                                    # 띠 경계 = 실제 화면 픽셀 줄(이음선 없음)
        for i, e in enumerate(c.profile):                      # e = 이 띠의 안쪽 가장자리
            r0, r1 = round(rows * i / STRIPS), round(rows * (i + 1) / STRIPS)
            if e <= 0.5 or r1 <= r0:
                continue
            x, y0, hh = 0 if self._left else w - e, r0 / dpr, (r1 - r0) / dpr
            p.drawPixmap(QRectF(x, y0, e, hh), pix, QRectF(0, r0, pw, r1 - r0))
            cw = min(CAST, e)
            p.drawPixmap(QRectF(x + e - cw if self._left else x, y0, cw, hh), cast, QRectF(cast.rect()))


class Curtain(QWidget):
    """커튼: 양옆에서 나와 가운데서 만나 살짝 튕기고, 잠시 닫혀 있다가 양옆으로 걷혀 옅어지며 스스로 사라진다.
    떠난 화면 그림(cover)이 있으면 닫히는 동안 그 위로 닫힌다. 이 위젯은 그리지 않는 틀이다.
    gl = GL 무대가 그린다: 천·떠난 화면 위젯 없이 상태(profile·alpha·cover)만 두고, GL이 그리는 순간 시각으로
    frame()을 불러 움직인다(타이머와 vsync가 엇갈려 프레임이 빠지지 않게). 시작은 부르는 쪽이 start()로
    (GL이 첫 화면을 낸 뒤 — 로딩 중 시간이 흘러 닫힘이 건너뛰지 않게)."""

    def __init__(self, parent, cover=None, gl=False):
        super().__init__(parent)
        self.gl = gl
        self.cover = cover if gl else None                # GL이 그리는 떠난 화면 그림(닫히는 동안만)
        self._t0 = None                                   # GL 커튼 시작 시각(perf_counter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(parent.rect())
        self.alpha, self.edges = 1.0, (0.0, 0.0)          # 투명도, 왼폭 안쪽 가장자리 x(레일, 밑단)
        self.profile = [0.0] * STRIPS                     # 띠마다 왼폭 안쪽 가장자리 x(위→아래)
        self._hem, self._hem_v, self._ms = 0.0, 0.0, 0.0
        self.cast =(_cast(True), _cast(False))
        self._under = _Under(self, *cover) if cover and not gl else None
        self._cloth = [] if gl else [_Cloth(self, left, body) for left in (True, False) for body in (True, False)]
        for w in ((self._under,) if self._under else ()) + tuple(self._cloth):
            w.setGeometry(self.rect() if w is self._under else QRect())
            w.show()
        self.raise_()
        self.setVisible(not gl)
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(CLOSE_MS + HOLD_MS + OPEN_MS)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(float(CLOSE_MS + HOLD_MS + OPEN_MS))
        if not gl:                                        # GL 커튼은 GL이 그릴 때 frame()으로 움직인다
            self.anim.valueChanged.connect(self._step)
        self.anim.finished.connect(self.hide)          # 지워지기 전에도 밑을 가리지 않게
        self.anim.finished.connect(self.deleteLater)
        if not gl:
            self.anim.start()
        parent.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == e.Type.Resize:                    # 무대·HUD 창 크기가 바뀌면 바로 따라감(다음 프레임까지 안 기다림)
            self.setGeometry(obj.rect())
            if self._under:
                self._under.setGeometry(self.rect())
        return False

    def start(self):
        self._t0 = time.perf_counter()
        self.anim.start()

    def running(self):
        return self._t0 is not None

    def frame(self):
        """GL이 그리기 직전에 — 지금 시각의 커튼 상태로."""
        if self._t0 is not None:
            self._step(min(self.anim.duration(), (time.perf_counter() - self._t0) * 1000))

    def fabric(self, left):
        return _fabric(math.ceil(self.width() / 2), self.height(), self.devicePixelRatioF(), left)

    def _step(self, ms):
        self.raise_()                                    # 늘 맨 앞 — 나중에 raise_한 버튼·재생바보다 위(이미 맨 앞이면 무비용)
        if ms < CLOSE_MS:
            rail = _closing(ms / CLOSE_MS)
        elif ms < CLOSE_MS + HOLD_MS:
            rail = CLOSED
        else:
            s = (ms - CLOSE_MS - HOLD_MS) / OPEN_MS
            rail = CLOSED - (CLOSED - GATHER) * QEasingCurve(QEasingCurve.Type.InOutCubic).valueForProgress(s)
            self.alpha = 1.0 - max(0.0, (s - 0.85) / 0.15)    # 다 걷힐 즈음 옅어짐
            if self._under and self._under.isVisible():
                self._under.hide()                       # 이제 새 화면 위로 걷힌다
            self.cover = None
        steps = max(0, math.ceil((ms - self._ms) / 4))   # 밑단 = 레일을 따라가는 감쇠 스프링(4ms 단위 적분)
        dt = (ms - self._ms) / 1000 / steps if steps else 0
        for _ in range(steps):
            self._hem_v += (HEM_K * (rail - self._hem) - HEM_C * self._hem_v) * dt
            self._hem = min(CLOSED + 0.04, max(0.0, self._hem + self._hem_v * dt))
        self._ms = ms
        half = self.width() / 2
        top, hem = self.edges = (rail * half, self._hem * half)
        # 안쪽 가장자리: 레일에 매인 위는 곧고 아래로 갈수록 더 처진다(밑단까지 곡선)
        self.profile = [top + (hem - top) * t ** 1.5 for t in ((i + 0.5) / STRIPS for i in range(STRIPS))]
        if not self.gl:
            self._place()

    def _place(self):
        w, h = self.width(), self.height()
        lo, hi = max(0, math.floor(min(self.profile))), math.ceil(max(self.profile))
        opaque = self.alpha >= 1.0
        for cloth in self._cloth:                        # 몸통 = 가장 안쪽으로 들어간 가장자리까지, 띠 = 나머지 굽은 부분
            x0, x1 = (0, lo) if cloth._body else (lo, hi)
            cloth.setGeometry(QRect(x0, 0, x1 - x0, h) if cloth._left else QRect(w - x1, 0, x1 - x0, h))
            cloth.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, opaque and cloth._body)
            cloth.update()


class CurtainStack(QStackedWidget):
    """화면 묶음 — 전환 직전 떠나는 화면을 찍어 둔다. 새 화면이 showEvent에서 여는 커튼이 그 위로 닫혔다 걷힌다."""

    def setCurrentIndex(self, i):
        self._shoot(self.widget(i))
        super().setCurrentIndex(i)

    def setCurrentWidget(self, w):
        self._shoot(w)
        super().setCurrentWidget(w)

    def _shoot(self, new):
        global _leaving
        old = self.currentWidget()
        if old is None or new is old or not old.isVisible() or reduced_motion():
            return
        win, origin = old.window(), old.mapToGlobal(QPoint())
        pix = win.grab(QRect(old.mapTo(win, QPoint()), old.size()))
        native = getattr(old, "paint_native", None)      # 위젯 grab에 안 잡히는 층(GL 무대·HUD 창)
        if native is not None:
            p = QPainter(pix)
            native(p, origin)
            p.end()
        _leaving = (pix, origin)


def open_curtain(stage: QWidget, gl=False):
    """stage(화면 또는 연주 무대) 위에 커튼을 닫았다 연다. 직전 화면 전환의 떠난 화면 그림이 있으면 그 위로 닫힌다.
    효과 축소면 생략. gl = GL 무대가 그리는 커튼(Curtain 참고 — 시작은 부르는 쪽이)."""
    global _leaving
    cover, _leaving = _leaving, None
    old = getattr(stage, "_curtain", None)
    if old is not None:
        old.anim.start()                                    # 아직 시작 전(GL 커튼)이어도 끝까지 보내 정리
        old.anim.setCurrentTime(old.anim.totalDuration())   # 정상 종료(직접 지우면 파괴 중 신호로 충돌)
    if reduced_motion():
        return None
    curtain = stage._curtain = Curtain(stage, cover, gl)
    curtain.anim.finished.connect(lambda: getattr(stage, "_curtain", None) is curtain and setattr(stage, "_curtain", None))
    return curtain
