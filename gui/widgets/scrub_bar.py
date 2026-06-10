"""스크럽 바 (브리프 §9.2).

- 곡 전체 가로 타임라인
- 코드 변경 눈금 + 코드명
- 현재 재생 헤드
- 루프 경계 표시
- 드래그 = 즉시 seek (스크럽 = 인덱스 점프, ML 재실행 없음 §3)
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QRectF, pyqtSignal

from gui import theme as T


class ScrubBar(QWidget):
    seekRequested = pyqtSignal(float)   # 초

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(52)
        self.setMouseTracking(True)
        self._timeline = None
        self._pos = 0.0
        self._dragging = False

    def set_timeline(self, timeline):
        self._timeline = timeline
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
        self._dragging = True
        self.seekRequested.emit(self._x_to_sec(e.position().x()))

    def mouseMoveEvent(self, e):
        if self._dragging:
            self.seekRequested.emit(self._x_to_sec(e.position().x()))

    def mouseReleaseEvent(self, e):
        self._dragging = False

    # ── 렌더 ─────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        track_y = h - 16
        track_h = 8

        p.setBrush(QColor(T.BORDER_SUBTLE))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, track_y, w, track_h), 4, 4)

        if not self._timeline or not self._timeline.segments:
            return

        segs = self._timeline.segments

        # 코드 변경 눈금(§6.1: text/dim)
        for seg in segs:
            if seg.start_bar != 0:
                x = self._sec_to_x(seg.start_sec)
                p.setPen(QPen(QColor(T.TEXT_DIM), 1))
                p.drawLine(int(x), track_y - 3, int(x), track_y + track_h + 3)

        # 재생된 부분
        head_x = self._sec_to_x(self._pos)
        p.setBrush(QColor(T.SCRUB_FILL))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, track_y, head_x, track_h), 4, 4)

        # 헤드 — 흰 원
        p.setBrush(QColor(T.SCRUB_HEAD))
        p.setPen(QPen(QColor(T.BORDER_DEFAULT), 1))
        p.drawEllipse(QRectF(head_x - 6, track_y + track_h / 2 - 6, 12, 12))
