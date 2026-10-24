"""짧은 화면 전환. 잠금 효과를 보존하고 재진입 시 이전 전환을 정리한다."""
from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QSequentialAnimationGroup, QPauseAnimation, QSettings
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget

DUR_MS = 180
STEP_MS = 0


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


def stagger(widgets, step: int = STEP_MS):
    for w in widgets:
        if w is not None and not w.isHidden():
            fade_in(w)
            break
