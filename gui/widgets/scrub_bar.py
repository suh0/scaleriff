"""스크럽 바 (정의서 §6 [3]).

- 곡 전체 가로 타임라인
- 코드 변경 눈금 + 코드명
- 현재 재생 헤드
- 루프 경계 표시
- 드래그 = 즉시 seek (스크럽 = 인덱스 점프, ML 재실행 없음 §4)
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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("곡 재생 위치")
        self.setToolTip("클릭·드래그로 이동 · 방향키로 5초 이동 · Home/End로 처음/끝")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._timeline = None
        self._pos = 0.0
        self._dragging = False
        self._hover_x = None

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
        track_y = h - 16
        track_h = 8

        p.setBrush(QColor(T.BORDER_SUBTLE))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, track_y, w, track_h), 4, 4)

        if not self._timeline or not self._timeline.segments:
            return

        segs = self._timeline.segments

        # 코드 변경 눈금(§6.1) — 비다이아토닉 구간은 빨강 강조(§3)
        for seg in segs:
            detour = getattr(seg, "is_detour", False)
            if seg.start_bar == 0 and not detour:
                continue
            x = self._sec_to_x(seg.start_sec)
            if detour:
                p.setPen(QPen(QColor(T.KEY_PRESSED_OUT), 2))
                p.drawLine(int(x), track_y - 6, int(x), track_y + track_h + 6)
            else:
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
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(T.BORDER_ACTIVE), 1))
            p.drawRoundedRect(QRectF(1, track_y - 5, w - 2, track_h + 10), 7, 7)
        if self._hover_x is not None:
            seconds = int(self._x_to_sec(self._hover_x))
            p.setFont(QFont(T.FONT_MONO, 9))
            p.setPen(QColor(T.TEXT_PRIMARY))
            x = max(0, min(w - 60, self._hover_x - 30))
            p.drawText(QRectF(x, 0, 60, 22), Qt.AlignmentFlag.AlignCenter,
                       f"{seconds // 60:02d}:{seconds % 60:02d}")
