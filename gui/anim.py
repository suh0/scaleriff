"""화면 전환 = 커튼: 새 화면을 덮은 커튼이 가운데서 양옆으로 걷힌다(스냅샷·흐림 없이 그리기만)."""
from __future__ import annotations

import math

from PyQt6.QtCore import (QEasingCurve, QSequentialAnimationGroup, QPauseAnimation, QSettings, QVariantAnimation,
                          Qt, QRectF)
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

CURTAIN_MS = 900    # 커튼이 걷히는 시간
CURTAIN_DELAY = 120 # 덮인 채 기다리는 시간
CURTAIN_FOLDS = 7   # 커튼 한 폭의 주름 수
CURTAIN_DARK, CURTAIN_LIGHT = QColor("#10153a"), QColor("#2b3584")   # 남색 벨벳(앱 남색 배경 톤)
CAST = 36           # 커튼 안쪽 가장자리 그늘 폭


def reduced_motion() -> bool:
    app = QApplication.instance()
    return bool(app and app.property("reduceMotion"))


def set_reduced_motion(on: bool):
    app = QApplication.instance()
    if app:
        app.setProperty("reduceMotion", bool(on))
    QSettings("graduation-project", "ScaleRiff").setValue("reduce_motion", bool(on))


class _Panel(QWidget):
    """커튼 한 폭(불투명) — 밑 화면은 커튼이 걷히며 드러나는 띠만 다시 그려진다.
    주름·조명은 한 번 구워 두고 폭에 맞춰 늘려 그린다(걷히며 주름이 모임)."""

    def __init__(self, parent, left):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._left, self._alpha, self._pix = left, 1.0, None

    def set_alpha(self, alpha):
        if alpha != self._alpha:
            self._alpha = alpha
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, alpha >= 1.0)   # 옅어질 땐 밑이 비침
            self.update()

    def _baked(self):
        full = self.parentWidget()
        w, h, dpr = math.ceil(full.width() / 2), full.height(), self.devicePixelRatioF()
        if self._pix is None or self._pix[0] != (w, h, dpr):
            pix = QPixmap(math.ceil(w * dpr), math.ceil(h * dpr))
            pix.setDevicePixelRatio(dpr)
            p = QPainter(pix)
            folds = QLinearGradient(0, 0, w, 0)
            for i in range(CURTAIN_FOLDS * 2 + 1):
                folds.setColorAt(i / (CURTAIN_FOLDS * 2), CURTAIN_DARK if i % 2 == 0 else CURTAIN_LIGHT)
            p.fillRect(QRectF(0, 0, w, h), folds)
            shade = QLinearGradient(0, 0, 0, h)                    # 위 조명·아래 그늘
            shade.setColorAt(0, QColor(255, 255, 255, 18))
            shade.setColorAt(1, QColor(0, 0, 0, 110))
            p.fillRect(QRectF(0, 0, w, h), shade)
            p.end()
            self._pix = ((w, h, dpr), pix)
        return self._pix[1]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setOpacity(self._alpha)
        pix = self._baked()
        p.drawPixmap(QRectF(self.rect()), pix, QRectF(pix.rect()))
        w, h = self.width(), self.height()
        edge = w if self._left else 0                              # 안쪽 가장자리 그늘
        cast = QLinearGradient(edge, 0, edge + (-CAST if self._left else CAST), 0)
        cast.setColorAt(0, QColor(0, 0, 0, 120))
        cast.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(w - CAST if self._left else 0, 0, CAST, h), cast)


class Curtain(QWidget):
    """커튼: 덮인 채 delay(ms) 기다렸다 가운데서 양옆으로 걷힌다 — 주름이 모이며 끝에서 옅어지고 스스로 사라진다.
    이 위젯은 그리지 않는 틀이고 좌우 두 폭(_Panel)만 움직인다."""

    def __init__(self, parent, delay=0):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._u = 0.0
        self._panels = (_Panel(self, True), _Panel(self, False))
        self.setGeometry(parent.rect())
        self._place()
        self.raise_()
        self.show()
        self.anim = QSequentialAnimationGroup(self)
        if delay:
            self.anim.addAnimation(QPauseAnimation(delay))
        opening = QVariantAnimation(self)
        opening.setDuration(CURTAIN_MS)
        opening.setStartValue(0.0)
        opening.setEndValue(1.0)
        opening.setEasingCurve(QEasingCurve.Type.InOutCubic)
        opening.valueChanged.connect(self._step)
        self.anim.addAnimation(opening)
        self.anim.finished.connect(self.hide)          # 지워지기 전에도 밑을 가리지 않게
        self.anim.finished.connect(self.deleteLater)
        self.anim.start()

    def _step(self, u):
        if self.size() != self.parentWidget().size():   # 첫 표시 직후 레이아웃이 무대 크기를 정해도 따라감
            self.setGeometry(self.parentWidget().rect())
            self.raise_()                                # 화면 resizeEvent가 올린 떠 있는 버튼보다 위로
        self._u = u
        self._place()

    def _place(self):
        w, h, u = self.width(), self.height(), self._u
        width = math.ceil(w / 2 * (1 - 0.9 * u))                   # 걷히며 양끝으로 모임
        left, right = self._panels
        left.setGeometry(0, 0, width, h)
        right.setGeometry(w - width, 0, width, h)
        alpha = 1.0 - max(0.0, (u - 0.85) / 0.15)                  # 다 걷힐 즈음 옅어짐
        left.set_alpha(alpha)
        right.set_alpha(alpha)


def open_curtain(stage: QWidget):
    """stage(화면 또는 연주 무대) 위에 커튼을 치고 연다. 효과 축소면 생략."""
    old = getattr(stage, "_curtain", None)
    if old is not None:
        old.anim.setCurrentTime(old.anim.totalDuration())   # 정상 종료(직접 지우면 파괴 중 신호로 충돌)
    if reduced_motion():
        return None
    curtain = stage._curtain = Curtain(stage, CURTAIN_DELAY)
    curtain.anim.finished.connect(lambda: getattr(stage, "_curtain", None) is curtain and setattr(stage, "_curtain", None))
    return curtain
