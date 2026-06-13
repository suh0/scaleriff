"""미니 스케일 가이드 — 한 옥타브 컴팩트 건반(HUD '다음 코드' 미리보기용).

피아노 위젯과 동일한 배지 색 규약(코드톤 초록 / 스케일음 회색 / 밖 빨강)으로
한 옥타브(C–B)만 작게 그려, 다음 구간의 스케일 모양을 미리 보여준다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QRectF

from analyze.theory import degree_number
from gui import theme as T

WHITE_PCS = [0, 2, 4, 5, 7, 9, 11]
BLACK_PCS = {1, 3, 6, 8, 10}

WHITE_RATIO = 2.6   # 흰 건반 세로:가로 비율(레터박스로 고정 → 찌그러짐 방지)


class MiniGuide(QWidget):
    """한 옥타브 미니 가이드. set_scale(note_set, chord_tones, scale_root).

    비율(WHITE_RATIO)을 유지하며 가용 영역 안에 가운데 정렬(레터박스).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._note_set: set[int] = set()
        self._chord_tones: set[int] = set()
        self._root = 0

    def set_scale(self, note_set, chord_tones, scale_root: int):
        self._note_set = set(note_set) if note_set else set()
        self._chord_tones = set(chord_tones) if chord_tones else set()
        self._root = scale_root
        self.update()

    def clear(self):
        self._note_set = set()
        self._chord_tones = set()
        self.update()

    def _state(self, pc: int) -> str:
        if not self._note_set:
            return "DEFAULT"
        if pc in self._chord_tones:
            return "CHORD"
        if pc in self._note_set:
            return "SCALE"
        return "OUT"

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        n = len(WHITE_PCS)
        # 비율 고정 + 가운데 정렬(레터박스) → 너비가 늘어도 안 찌그러짐
        kw = w / n
        kh = kw * WHITE_RATIO
        if kh > h:
            kh = h
            kw = kh / WHITE_RATIO
        x0 = (w - kw * n) / 2.0
        y0 = (h - kh) / 2.0
        bw = kw * 0.6
        bh = kh * 0.6

        # 흰 건반
        for i, pc in enumerate(WHITE_PCS):
            r = QRectF(x0 + i * kw + 1, y0, kw - 2, kh - 1)
            self._draw_key(p, pc, r, white=True)
        # 검은 건반
        for i, pc in enumerate(WHITE_PCS):
            if (pc + 1) in BLACK_PCS:
                rx = x0 + (i + 1) * kw - bw / 2
                self._draw_key(p, pc + 1, QRectF(rx, y0, bw, bh), white=False)

    def _draw_key(self, p: QPainter, pc: int, r: QRectF, white: bool):
        st = self._state(pc)
        p.setBrush(QColor(T.KEY_W_FILL if white else T.KEY_B_FILL))
        p.setPen(QPen(QColor(T.KEY_W_BORDER), 1.0) if white else Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 2, 2)
        if st == "DEFAULT":
            return
        # 배지(작은 동그라미 + 도수)
        if st == "CHORD":
            bg, fg = QColor(T.BADGE_CHORD), QColor(T.BADGE_TEXT)
        elif st == "SCALE":
            bg, fg = QColor(T.BADGE_SCALE), QColor(T.BADGE_SCALE_TEXT)
        else:
            bg, fg = QColor(T.BADGE_OUT), QColor(T.BADGE_TEXT)
        sz = min(r.width() * 0.8, 15)
        cx = r.x() + r.width() / 2
        cy = r.y() + r.height() - sz / 2 - 2
        badge = QRectF(cx - sz / 2, cy - sz / 2, sz, sz)
        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(badge)
        text = "×" if st == "OUT" else degree_number(pc, self._root)
        if text:
            f = QFont(T.FONT_MONO)
            f.setPixelSize(max(7, int(sz * 0.5)))
            f.setBold(True)
            p.setFont(f)
            p.setPen(fg)
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
