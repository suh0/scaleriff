"""코드 레인 — 타임라인 중심 스크럽/HUD 통합 위젯 (§6 [3], C안).

고정 플레이헤드(폭 34% 지점)로 코드 블록이 흘러들어온다:
지난 블록 dim · 현재 블록 강조 · 다음 블록은 큰 코드명과 스케일명으로 표시.
레인 드래그 = 시킹, 블록 클릭 = 그 구간 시작으로 점프. 켜진 루프 스팬 표시.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetricsF, QPolygonF
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal

from gui import theme as T

HEAD_RATIO = 0.12    # 고정 플레이헤드 x 위치(폭 비율) — 왼쪽 끝에서 조금 안쪽
BAR_PX = 110         # 한 마디의 픽셀 폭 → px_per_sec 산출
DRAG_PX = 4          # 이 이상 움직이면 클릭이 아니라 드래그-시킹


class ChordLane(QWidget):
    seekRequested = pyqtSignal(float)   # 초

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(84)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("코드를 클릭하면 해당 구간으로 이동합니다. 드래그하면 재생 위치를 옮깁니다.")
        self._timeline = None
        self._pos = 0.0
        self._press_x: float | None = None
        self._press_sec = 0.0
        self._dragging = False

    def set_timeline(self, timeline):
        self._timeline = timeline
        self._pos = 0.0
        self.update()

    def set_position(self, sec: float):
        self._pos = sec
        self.update()

    # ── 시간↔x: 플레이헤드 고정, 블록이 흐름 ────────────────────
    def _pps(self) -> float:
        tl = self._timeline
        bar_sec = (tl.time_sig_beats() * tl.beat_sec()) if tl else 2.0
        return BAR_PX / bar_sec if bar_sec > 0 else 55.0

    def _head_x(self) -> float:
        return self.width() * HEAD_RATIO

    def _sec_to_x(self, sec: float) -> float:
        return self._head_x() + (sec - self._pos) * self._pps()

    def _x_to_sec(self, x: float) -> float:
        return self._pos + (x - self._head_x()) / self._pps()

    # ── 인터랙션: 드래그=시킹 / 클릭=블록 점프 ──────────────────
    def mousePressEvent(self, e):
        self._press_x = e.position().x()
        self._press_sec = self._pos
        self._dragging = False

    def mouseMoveEvent(self, e):
        if self._press_x is None or not self._timeline:
            return
        dx = e.position().x() - self._press_x
        if not self._dragging and abs(dx) < DRAG_PX:
            return
        self._dragging = True      # 레인 내용을 끄는 방향(오른쪽 드래그=과거로)
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        sec = self._press_sec - dx / self._pps()
        self.seekRequested.emit(max(0.0, min(self._timeline.total_sec(), sec)))

    def mouseReleaseEvent(self, e):
        if self._press_x is None:
            return
        was_drag, x = self._dragging, e.position().x()
        self._press_x = None
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        if was_drag or not self._timeline:
            return
        seg = self._timeline.segment_at(self._x_to_sec(x))   # 클릭 → 구간 점프
        if seg is not None:
            self.seekRequested.emit(seg.start_sec)

    # ── 렌더 ─────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setBrush(QColor(T.BG_INSET))
        p.setPen(QPen(QColor(T.BORDER_SUBTLE), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)
        tl = self._timeline
        if not tl or not tl.segments:
            return
        p.setClipRect(QRectF(1, 1, w - 2, h - 2))

        cur = tl.segment_at(self._pos)

        # 켜진 루프 스팬 — 은은한 배경
        bars = tl.bar_times
        for lp in getattr(tl, "loops", []) or []:
            if not lp.get("on") or lp["end_bar"] + 1 >= len(bars):
                continue
            x0 = self._sec_to_x(lp.get("start_sec", bars[lp["start_bar"]]))
            x1 = self._sec_to_x(lp.get("end_sec", bars[lp["end_bar"] + 1]))
            p.setBrush(QColor(255, 255, 255, 14))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(QRectF(x0, 1, x1 - x0, h - 2))

        name_f = QFont(T.FONT_SANS_EN)
        name_f.setBold(True)
        kind_f = QFont(T.FONT_MONO)
        kind_f.setPixelSize(10)
        for seg in tl.segments:
            x0 = self._sec_to_x(seg.start_sec)
            x1 = self._sec_to_x(seg.end_sec)
            if x1 < 0 or x0 > w:
                continue
            is_cur = seg is cur
            is_past = seg.end_sec <= self._pos
            if is_cur:      # 현재 블록 강조 배경
                p.setBrush(QColor(T.BG_SURFACE))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRect(QRectF(x0, 1, x1 - x0, h - 2))
                p.setBrush(QColor(T.BORDER_ACTIVE))
                p.drawRect(QRectF(x0, h - 4, x1 - x0, 3))
            # 경계선 — 비다이아토닉 진입은 빨강(기존 스크럽 규약)
            detour = getattr(seg, "is_detour", False)
            p.setPen(QPen(QColor(T.BADGE_OUT if detour else T.BORDER_SUBTLE),
                          2 if detour else 1))
            p.drawLine(int(x0), 4, int(x0), h - 4)
            # 코드명 + 스케일 종류
            if is_past:
                name_c, kind_c = T.TEXT_DIM, T.TEXT_DIM
            elif is_cur:
                name_c, kind_c = T.TEXT_PRIMARY, T.TEXT_MUTED
            else:
                name_c, kind_c = T.TEXT_MUTED, T.TEXT_DIM
            name_f.setPixelSize(18 if is_past else 26)
            has_scale = bool(seg.scale and x1 - x0 > 60)
            name_metrics = QFontMetricsF(name_f)
            kind_metrics = QFontMetricsF(kind_f)
            text_h = name_metrics.height()
            if has_scale:
                text_h += 2 + kind_metrics.height()
            text_y = (h - text_h) / 2
            p.setFont(name_f)
            p.setPen(QColor(name_c))
            tx = x0 + 12
            p.save()
            p.setClipRect(QRectF(x0 + 2, 2, max(0, x1 - x0 - 4), h - 4), Qt.ClipOperation.IntersectClip)
            p.drawText(QPointF(tx, text_y + name_metrics.ascent()), seg.chord.name)
            if has_scale:
                p.setFont(kind_f)
                p.setPen(QColor(kind_c))
                kind_y = text_y + name_metrics.height() + 2
                p.drawText(QPointF(tx, kind_y + kind_metrics.ascent()), seg.scale.kind)
            p.restore()

        # 고정 플레이헤드(세로선 + 위 삼각형)
        hx = self._head_x()
        p.setPen(QPen(QColor(T.SCRUB_HEAD), 2))
        p.drawLine(int(hx), 1, int(hx), h - 1)
        p.setBrush(QColor(T.SCRUB_HEAD))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(hx - 6, 1), QPointF(hx + 6, 1),
                                 QPointF(hx, 9)]))
