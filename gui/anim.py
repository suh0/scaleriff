"""짧은 화면 전환. 잠금 효과를 보존하고 재진입 시 이전 전환을 정리한다."""
from __future__ import annotations

import time

from PyQt6.QtCore import (QPropertyAnimation, QEasingCurve, QSequentialAnimationGroup, QPauseAnimation, QSettings,
                          QVariantAnimation, Qt, QRectF, QPointF, pyqtProperty)
from PyQt6.QtGui import QColor, QLinearGradient, QPainter
from PyQt6.QtWidgets import QApplication, QGraphicsEffect, QStackedWidget, QWidget

from gui.theme import paint_backdrop   # 화면들은 투명 — 전환 가림막도 창 공통 배경과 같은 그림

DUR_MS = 180
OUT_MS = 200        # 화면 전환 ① 이전 화면 스냅샷이 흐려지며 사라짐(새 화면은 배경으로 가림)
IN_MS = 180         # 화면 전환 ② 가림막(배경)이 걷히며 새 화면 등장 — 박스 순차 등장도 이때부터
BLUR = 6            # 흐림 정도 = 축소 배율 - 1(줄였다 부드럽게 늘려 흐리게 — 블러 필터보다 훨씬 쌈)
STEP_MS = 70        # 박스 순차 등장 간격
CURTAIN_MS = 900    # 무대 커튼이 걷히는 시간
CURTAIN_FOLDS = 7   # 커튼 한 폭의 주름 수
CURTAIN_DARK, CURTAIN_LIGHT = QColor("#10153a"), QColor("#2b3584")   # 남색 벨벳(앱 남색 배경 톤)
_hold_until = 0.0   # 진행 중 전환의 ①이 끝나는 시각(perf_counter) — 그 전엔 새 화면 박스를 띄우지 않음


def reduced_motion() -> bool:
    app = QApplication.instance()
    return bool(app and app.property("reduceMotion"))


def _clear_entry(w):
    group = getattr(w, "_entry_animation", None)
    if group is not None:
        group.stop()
        group.deleteLater()
        w._entry_animation = None
    effect = getattr(w, "_entry_effect", None)
    if effect is not None and w.graphicsEffect() is effect:
        w.setGraphicsEffect(None)
    w._entry_effect = None


def set_reduced_motion(on: bool):
    app = QApplication.instance()
    if app:
        app.setProperty("reduceMotion", bool(on))
        if on:
            for w in app.allWidgets():
                if getattr(w, "_entry_animation", None) is not None:
                    _clear_entry(w)
    QSettings("graduation-project", "ScaleRiff").setValue("reduce_motion", bool(on))


def _blurred(pix, k):
    """pix를 1/k로 줄였다 늘린 흐린 그림의 작은 원본(그릴 때 SmoothPixmapTransform으로 늘림)."""
    return pix.scaled(max(1, round(pix.width() / k)), max(1, round(pix.height() / k)),
                      Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


class _Soft(QGraphicsEffect):
    """등장 효과: t 0 = 투명·흐림 → 1 = 선명. opacity()는 QGraphicsOpacityEffect와 같은 뜻(투명도)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = 0.0

    def opacity(self):
        return self._t

    def _get(self):
        return self._t

    def _set(self, t):
        self._t = t
        self.update()

    t = pyqtProperty(float, _get, _set)

    def draw(self, p):
        if self._t >= 1.0:
            self.drawSource(p)
            return
        pix, off = self.sourcePixmap(Qt.CoordinateSystem.LogicalCoordinates)
        p.save()
        p.setOpacity(p.opacity() * self._t)
        k = 1 + BLUR * (1 - self._t)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target = QRectF(QPointF(off), pix.deviceIndependentSize())
        src = _blurred(pix, k) if k > 1.05 else pix
        p.drawPixmap(target, src, QRectF(src.rect()))
        p.restore()


def fade_in(w: QWidget, delay: int = 0):
    _clear_entry(w)
    if reduced_motion() or w.graphicsEffect() is not None:
        return
    effect = _Soft(w)
    w.setGraphicsEffect(effect)
    group = QSequentialAnimationGroup(w)
    if delay:
        group.addAnimation(QPauseAnimation(delay))
    animation = QPropertyAnimation(effect, b"t")
    animation.setDuration(DUR_MS)
    animation.setStartValue(0)
    animation.setEndValue(1)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    group.addAnimation(animation)
    w._entry_animation, w._entry_effect = group, effect
    group.finished.connect(lambda: _clear_entry(w))
    group.start()


def stagger(boxes, step: int = STEP_MS):
    """박스 단위 순차 등장(위 → 아래). 항목이 튜플/리스트면 한 박스로 같이 나타난다.

    화면 전환 중이면 이전 화면이 사라진 뒤(①)부터 시작한다. 숨은 박스는 건너뛴다.
    """
    base = max(0, round((_hold_until - time.perf_counter()) * 1000))
    groups = [[w for w in (b if isinstance(b, (tuple, list)) else (b,)) if w is not None and not w.isHidden()]
              for b in boxes]
    for i, group in enumerate(g for g in groups if g):
        for w in group:
            fade_in(w, base + i * step)


class _Snapshot(QWidget):
    """전환 가림막: ① 배경 위 이전 화면 이미지가 흐려지며 사라짐 → ② 배경 가림막이 걷히며 새 화면 등장."""

    def __init__(self, parent, pixmap):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pixmap, self._ms = pixmap, 0.0
        self._soft = _blurred(pixmap, 1 + BLUR)          # 흐린 그림은 한 번만 만들어 둔다
        self.setGeometry(parent.rect())
        self.raise_()
        self.show()
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(OUT_MS + IN_MS)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(float(OUT_MS + IN_MS))
        self.anim.valueChanged.connect(self._step)
        self.anim.finished.connect(self.deleteLater)
        self.anim.start()

    def _step(self, ms):
        self._ms = ms
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        ease = QEasingCurve(QEasingCurve.Type.OutCubic)
        if self._ms < OUT_MS:
            u = ease.valueForProgress(self._ms / OUT_MS)
            paint_backdrop(p, self.width(), self.height())
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.setOpacity(1.0 - u)                       # 흐린 그림 위에 선명한 그림이 먼저 옅어짐 = 흐려지며 사라짐
            p.drawPixmap(QRectF(self.rect()), self._soft, QRectF(self._soft.rect()))
            p.setOpacity((1.0 - u) ** 2)
            p.drawPixmap(0, 0, self._pixmap)
        else:
            p.setOpacity(1.0 - ease.valueForProgress((self._ms - OUT_MS) / IN_MS))
            paint_backdrop(p, self.width(), self.height())


class FadeStack(QStackedWidget):
    """화면 전환: 이전 화면이 다 사라진 뒤 새 화면이 나타난다(스냅샷 한 장 + 배경 가림막, 위젯 효과 없음).

    새 화면은 가림막 아래에서 이미 현재 화면이고, 그 화면의 박스 순차 등장(stagger)은 ①이 끝난 뒤 시작한다.
    """
    _snapshot = None

    def setCurrentWidget(self, w):
        global _hold_until
        old = self.currentWidget()
        if old is None or old is w or reduced_motion() or not self.isVisible():
            return super().setCurrentWidget(w)
        # 화면들은 투명 — 부모(창 공통 배경)째 찍어야 배경 없는 밝은 판이 번쩍이지 않는다(연달아 전환하면 이전 가림막 포함)
        parent = self.parentWidget()
        shot = parent.grab(self.geometry()) if parent is not None else self.grab()
        if self._snapshot is not None:          # 이전 전환은 끝으로 보내 정상 종료(직접 지우면 파괴 중 신호로 충돌)
            self._snapshot.anim.setCurrentTime(OUT_MS + IN_MS)
        _hold_until = time.perf_counter() + OUT_MS / 1000    # 새 화면 showEvent의 stagger보다 먼저
        super().setCurrentWidget(w)
        snap = self._snapshot = _Snapshot(self, shot)
        snap.anim.finished.connect(lambda: self._snapshot is snap and setattr(self, "_snapshot", None))


class Curtain(QWidget):
    """무대 커튼: 덮인 채 delay(ms) 기다렸다 가운데서 양옆으로 걷힌다 — 주름이 모이며 끝에서 옅어지고 스스로 사라진다."""

    def __init__(self, parent, delay=0):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._u = 0.0
        self.setGeometry(parent.rect())
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
        self.anim.finished.connect(self.deleteLater)
        self.anim.start()

    def _step(self, u):
        self._u = u
        if self.size() != self.parentWidget().size():   # 첫 표시 직후 레이아웃이 무대 크기를 정해도 따라감
            self.setGeometry(self.parentWidget().rect())
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h, u = self.width(), self.height(), self._u
        p.setOpacity(1.0 - max(0.0, (u - 0.85) / 0.15))          # 다 걷힐 즈음 옅어짐
        width = w / 2 * (1 - 0.9 * u)                              # 걷히며 양끝으로 모임(주름 압축)
        for left in (True, False):
            x0 = 0.0 if left else w - width
            folds = QLinearGradient(x0, 0, x0 + width, 0)
            for i in range(CURTAIN_FOLDS * 2 + 1):
                folds.setColorAt(i / (CURTAIN_FOLDS * 2), CURTAIN_DARK if i % 2 == 0 else CURTAIN_LIGHT)
            p.fillRect(QRectF(x0, 0, width, h), folds)
            shade = QLinearGradient(0, 0, 0, h)                    # 위 조명·아래 그늘
            shade.setColorAt(0, QColor(255, 255, 255, 18))
            shade.setColorAt(1, QColor(0, 0, 0, 110))
            p.fillRect(QRectF(x0, 0, width, h), shade)
            edge = x0 + width if left else x0                      # 안쪽 가장자리 그림자가 무대에 드리움
            cast = QLinearGradient(edge, 0, edge + (36 if left else -36), 0)
            cast.setColorAt(0, QColor(0, 0, 0, 120))
            cast.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(QRectF(min(edge, edge + (36 if left else -36)), 0, 36, h), cast)


def open_curtain(stage: QWidget):
    """무대(stage) 위에 커튼을 치고 연다. 화면 전환 중이면 이전 화면이 사라진 뒤 열린다. 효과 축소면 생략."""
    old = getattr(stage, "_curtain", None)
    if old is not None:
        old.anim.setCurrentTime(old.anim.totalDuration())   # 정상 종료(직접 지우면 파괴 중 신호로 충돌)
    if reduced_motion():
        return None
    curtain = stage._curtain = Curtain(stage, max(0, round((_hold_until - time.perf_counter()) * 1000)) + 120)
    curtain.anim.finished.connect(lambda: getattr(stage, "_curtain", None) is curtain and setattr(stage, "_curtain", None))
    return curtain
