"""짧은 화면 전환. 잠금 효과를 보존하고 재진입 시 이전 전환을 정리한다."""
from __future__ import annotations

import time

from PyQt6.QtCore import (QPropertyAnimation, QEasingCurve, QSequentialAnimationGroup, QPauseAnimation, QSettings,
                          QVariantAnimation, Qt)
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QStackedWidget, QWidget

from gui.theme import paint_backdrop   # 화면들은 투명 — 전환 가림막도 창 공통 배경과 같은 그림

DUR_MS = 180
OUT_MS = 200        # 화면 전환 ① 이전 화면 스냅샷이 떠오르며 사라짐(새 화면은 배경으로 가림)
IN_MS = 180         # 화면 전환 ② 가림막(배경)이 걷히며 새 화면 등장 — 박스 순차 등장도 이때부터
SWITCH_RISE = 12    # 사라지며 위로 떠오르는 거리(px)
STEP_MS = 70        # 박스 순차 등장 간격
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


def fade_in(w: QWidget, delay: int = 0):
    _clear_entry(w)
    if reduced_motion() or w.graphicsEffect() is not None:
        return
    effect = QGraphicsOpacityEffect(w)
    effect.setOpacity(0)
    w.setGraphicsEffect(effect)
    group = QSequentialAnimationGroup(w)
    if delay:
        group.addAnimation(QPauseAnimation(delay))
    animation = QPropertyAnimation(effect, b"opacity")
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
    """전환 가림막: ① 배경 위 이전 화면 이미지가 떠오르며 사라짐 → ② 배경 가림막이 걷히며 새 화면 등장."""

    def __init__(self, parent, pixmap):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._pixmap, self._ms = pixmap, 0.0
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
            p.setOpacity(1.0 - u)
            p.drawPixmap(0, round(-SWITCH_RISE * u), self._pixmap)
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
