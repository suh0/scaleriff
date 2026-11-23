"""스크럽 바 (정의서 §6 [3]).

- 곡 전체 가로 타임라인
- 현재 재생 헤드
- 드래그 = 즉시 seek (스크럽 = 인덱스 점프, ML 재실행 없음 §4)
"""
from __future__ import annotations

import math

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSignal

from gui import theme as T


class ScrubBar(QWidget):
    seekRequested = pyqtSignal(float)   # 초

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(36)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("곡 재생 위치")
        self.setToolTip("클릭·드래그로 이동 · 방향키로 5초 이동 · Home/End로 처음/끝")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._timeline = None
        self._bars = []
        self._pos = 0.0
        self._dragging = False
        self._hover_x = None
        self._kb_focus = False            # 키보드(Tab)로 들어온 포커스만 테두리 표시

    def set_timeline(self, timeline):
        self._timeline = timeline
        self._bars = []                               # 마디 시작 = 눈금(검출 마디 없으면 BPM으로 등간격)
        if timeline:
            bar = timeline.beat_sec() * timeline.time_sig_beats()
            self._bars = (list(timeline.bar_times) if len(timeline.bar_times) >= 2 else
                          [i * bar for i in range(int(timeline.total_sec() / bar) + 1)])
        self.update()

    def set_position(self, sec: float):
        self._pos = sec
        self.update()

    def _total(self) -> float:
        return self._timeline.total_sec() if self._timeline else 1.0

    def _x_to_sec(self, x: float) -> float:
        w = max(1, self.width())
        return max(0.0, min(self._total(), x / w * self._total()))

    def _sec_to_x(self, sec: float) -> float:
        total = self._total() or 1.0
        return sec / total * self.width()

    # ── 마우스 = seek ────────────────────────────────────────────
    def mousePressEvent(self, e):
        self.setFocus()
        self._dragging = True
        self.seekRequested.emit(self._x_to_sec(e.position().x()))

    def mouseMoveEvent(self, e):
        self._hover_x = e.position().x()
        self.update()
        if self._dragging:
            self.seekRequested.emit(self._x_to_sec(e.position().x()))

    def mouseReleaseEvent(self, e):
        self._dragging = False

    def focusInEvent(self, event):
        self._kb_focus = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        super().focusInEvent(event)

    def leaveEvent(self, event):
        self._hover_x = None
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        targets = {Qt.Key.Key_Left: self._pos - 5, Qt.Key.Key_Right: self._pos + 5,
                   Qt.Key.Key_Home: 0, Qt.Key.Key_End: self._total()}
        if event.key() in targets:
            self.seekRequested.emit(max(0, min(self._total(), targets[event.key()])))
            event.accept()
        else:
            super().keyPressEvent(event)

    # ── 렌더 ─────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        y = h * 0.6                       # 가는 네온 선 높이(위쪽은 호버 시각 자리)

        def line(x0, x1, color, alpha, width):
            c = QColor(color)
            c.setAlpha(alpha)
            p.setPen(QPen(c, width, cap=Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(x0, y), QPointF(x1, y))

        line(0, w, T.NEON, 160, 2.0)
        if not self._timeline or not self._timeline.segments:
            return
        # 마디 눈금: 화면에서 36px 이상 떨어지게 몇 마디씩 건너뛴다
        step = max(1, math.ceil(len(self._bars) * 36 / max(1, w)))
        tick = QColor(T.NEON_LIGHT)
        tick.setAlpha(90)
        p.setPen(QPen(tick, 1.5))
        for when in self._bars[::step]:
            x = self._sec_to_x(when)
            p.drawLine(QPointF(x, y - 5), QPointF(x, y + 5))

        # 재생된 부분 = 번진 빛 + 밝은 심
        head_x = self._sec_to_x(self._pos)
        line(0, head_x, T.NEON, 70, 7.0)
        line(0, head_x, T.NEON_LIGHT, 255, 2.0)
        # 헤드 = 빛나는 세로 막대
        for width, alpha in ((9.0, 60), (3.0, 255)):
            c = QColor(T.NEON_LIGHT)
            c.setAlpha(alpha)
            p.setPen(QPen(c, width, cap=Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(head_x, y - 12), QPointF(head_x, y + 12))
        if self.hasFocus() and self._kb_focus:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(T.BORDER_ACTIVE), 1))
            p.drawRoundedRect(QRectF(1, y - 14, w - 2, 28), 7, 7)
        if self._hover_x is not None:
            seconds = int(self._x_to_sec(self._hover_x))
            p.setFont(QFont(T.FONTS, 9))
            p.setPen(QColor(T.TEXT_PRIMARY))
            x = max(0, min(w - 60, self._hover_x - 30))
            p.drawText(QRectF(x, 0, 60, 22), Qt.AlignmentFlag.AlignCenter,
                       f"{seconds // 60:02d}:{seconds % 60:02d}")
