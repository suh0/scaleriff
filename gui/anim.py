"""입장 애니메이션 — 위젯 순차 페이드인(스태거).

각 화면이 showEvent에서 stagger([위젯…])를 부르면 위에서부터 차례로 떠오른다.
효과는 애니메이션이 끝나면 제거해 다른 QGraphicsOpacityEffect(잠금·카드)와
충돌하지 않는다.
"""
from __future__ import annotations

from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QTimer
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

DUR_MS = 320    # 페이드인 시간
STEP_MS = 80    # 위젯 간 시차


def fade_in(w: QWidget, delay: int = 0):
    eff = QGraphicsOpacityEffect(w)
    eff.setOpacity(0.0)
    w.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity", w)
    a.setDuration(DUR_MS)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.Type.OutCubic)
    a.finished.connect(lambda: w.setGraphicsEffect(None))
    if delay > 0:
        QTimer.singleShot(delay, a.start)
    else:
        a.start()


def stagger(widgets, step: int = STEP_MS):
    for i, w in enumerate(widgets):
        if w is not None:
            fade_in(w, i * step)
