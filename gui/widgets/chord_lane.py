"""코드 레인 — 타임라인 중심 스크럽/HUD 통합 위젯 (§6 [3], C안).

고정 플레이헤드(폭 34% 지점)로 코드 블록이 흘러들어온다:
지난 블록 dim · 현재 블록 강조 · 바로 다음 블록엔 미니 건반 미리보기 내장.
레인 드래그 = 시킹, 블록 클릭 = 그 구간 시작으로 점프. 켜진 루프 스팬 표시.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QPolygonF
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal

from gui import theme as T

WHITE_PCS = [0, 2, 4, 5, 7, 9, 11]
BLACK_PCS = {1, 3, 6, 8, 10}
HEAD_RATIO = 0.12    # 고정 플레이헤드 x 위치(폭 비율) — 왼쪽 끝에서 조금 안쪽
BAR_PX = 110         # 한 마디의 픽셀 폭 → px_per_sec 산출
DRAG_PX = 4          # 이 이상 움직이면 클릭이 아니라 드래그-시킹


class ChordLane(QWidget):
    seekRequested = pyqtSignal(float)   # 초

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(92)
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
        sec = self._press_sec - dx / self._pps()
        self.seekRequested.emit(max(0.0, min(self._timeline.total_sec(), sec)))

    def mouseReleaseEvent(self, e):
        if self._press_x is None:
            return
        was_drag, x = self._dragging, e.position().x()
        self._press_x = None
        self._dragging = False
        if was_drag or not self._timeline:
            return
        seg = self._timeline.segment_at(self._x_to_sec(x))   # 클릭 → 구간 점프
        if seg is not None:
            self.seekRequested.emit(seg.start_sec)

    # ── 렌더 ─────────────────────────────────────────────────────
    def _draw_mini(self, p: QPainter, r: QRectF, note_set, chord_tones, root=-1):
        """블록 안 한 옥타브 미니 건반 — 코드톤 초록(근음 파랑)/스케일 회색."""
        kw = r.width() / 7
        for i, pc in enumerate(WHITE_PCS):
            kr = QRectF(r.x() + i * kw + 0.5, r.y(), kw - 1, r.height())
            p.setBrush(QColor(T.KEY_W_FILL))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(kr, 1.5, 1.5)
        bw, bh = kw * 0.6, r.height() * 0.55
        for i, pc in enumerate(WHITE_PCS):
            if (pc + 1) in BLACK_PCS:
                p.setBrush(QColor(T.KEY_B_FILL))
                p.drawRect(QRectF(r.x() + (i + 1) * kw - bw / 2, r.y(), bw, bh))
        sz = min(kw * 0.7, 9.0)
        for pc in (note_set or []):
            st_chord = pc in (chord_tones or [])
            if pc in BLACK_PCS:
                i = WHITE_PCS.index(pc - 1)
                cx = r.x() + (i + 1) * kw
                cy = r.y() + bh - sz / 2 - 1
            else:
                i = WHITE_PCS.index(pc)
                cx = r.x() + (i + 0.5) * kw
                cy = r.y() + r.height() - sz / 2 - 1.5
            if st_chord:
                col = T.BADGE_ROOT if pc == root % 12 else T.BADGE_CHORD
            else:
                col = T.BADGE_SCALE
            p.setBrush(QColor(col))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(cx - sz / 2, cy - sz / 2, sz, sz))

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
            x0 = self._sec_to_x(bars[lp["start_bar"]])
            x1 = self._sec_to_x(bars[lp["end_bar"] + 1])
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
            name_f.setPixelSize(26 if is_cur else 18)
            p.setFont(name_f)
            p.setPen(QColor(name_c))
            tx = x0 + 12
            p.drawText(QPointF(tx, 30 if is_cur else 26), seg.chord.name)
            if seg.scale and x1 - x0 > 60:
                p.setFont(kind_f)
                p.setPen(QColor(kind_c))
                p.drawText(QPointF(tx, 44), seg.scale.kind)
            # 미니 건반 미리보기 — 아직 안 끝난 모든 블록(끝나야 소멸).
            # 매 프레임 보이는 블록만 그리므로 블록 수 × 미니 1개 — 오버헤드 미미.
            mw = min(104.0, (x1 - x0) - 16)     # 짧은 마디는 폭에 맞춰 축소
            if not is_past and mw >= 36:
                self._draw_mini(p, QRectF(tx, h - 34, mw, 26),
                                seg.note_set, seg.chord_tones(), seg.chord.root)

        # 고정 플레이헤드(세로선 + 위 삼각형)
        hx = self._head_x()
        p.setPen(QPen(QColor(T.SCRUB_HEAD), 2))
        p.drawLine(int(hx), 1, int(hx), h - 1)
        p.setBrush(QColor(T.SCRUB_HEAD))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPolygon(QPolygonF([QPointF(hx - 6, 1), QPointF(hx + 6, 1),
                                 QPointF(hx, 9)]))
