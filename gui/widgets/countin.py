"""카운트인 표시등 — 다음 코드 전환까지 남은 박(최대 4박)을 점등으로 표시.

구간 끝(=다음 코드 시작) 4박 전부터 4→3→2→1 카운트다운 점등.
재생 중 매 틱 set_remaining(beats_left)로 갱신한다.
"""
from __future__ import annotations

import math

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QRectF

from gui import theme as T

DOTS = 4


class CountIn(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._lit = 0          # 점등 개수(0이면 비활성)

    def set_remaining(self, beats_left):
        """beats_left: 다음 코드까지 남은 박(float) 또는 None."""
        if beats_left is None or beats_left <= 0 or beats_left > DOTS:
            lit = 0
        else:
            lit = max(1, min(DOTS, math.ceil(beats_left)))
        if lit != self._lit:
            self._lit = lit
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = self.height()
        d = min(14, h - 6)
        gap = 7
        x = 0.0

        # 라벨
        f = QFont(T.FONT_MONO); f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor(T.TEXT_DIM if self._lit == 0 else T.TEXT_MUTED))
        lab = "다음 코드까지"
        p.drawText(QRectF(0, 0, 78, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, lab)
        x = 82.0

        cy = h / 2
        for i in range(DOTS):
            on = i < self._lit
            p.setBrush(QColor(T.BADGE_OUT if on else T.BG_SURFACE_ALT))
            p.setPen(QPen(QColor(T.BORDER_DEFAULT), 1) if not on else Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(x, cy - d / 2, d, d))
            x += d + gap

        # 카운트 숫자
        if self._lit > 0:
            fn = QFont(T.FONT_MONO); fn.setPixelSize(13); fn.setBold(True)
            p.setFont(fn)
            p.setPen(QColor(T.TEXT_PRIMARY))
            p.drawText(QRectF(x + 2, 0, 22, h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       str(self._lit))
