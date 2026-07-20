"""리프 뷰 — 리프연습 모드에서 생성된 ML 리프를 '스케일 번호 + 박자'로 표시.

현재 구간의 example_phrase(=[{midi, beat_pos, dur_beats}])를 박자 격자 위에
음표 알약으로 그린다. 각 음표 = 스케일 도수 번호(코드 근음/스케일 기준)로 라벨,
가로 위치 = 박자(beat_pos). 재생 중에는 진행 헤드와 현재 음을 강조한다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QRectF

from analyze.theory import degree_number
from gui import theme as T


class RiffView(QWidget):
    """ML 리프 한 구간을 박자 격자에 표시."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._notes: list[dict] = []
        self._root = 0
        self._note_set: set[int] = set()
        self._chord_tones: set[int] = set()
        self._beats_per_bar = 4
        self._total_beats = 8.0
        self._rel_beat = -1.0   # 재생 헤드(구간 시작 기준 박), <0이면 숨김

    def set_segment(self, seg, bpm: float, beats_per_bar: int):
        self._beats_per_bar = max(1, beats_per_bar)
        # 가이드는 늘 1마디만 표시 — 같은 코드가 여러 마디 반복돼도 1마디 고정(§3).
        #   리프는 1마디 단위로 반복되므로 첫 마디만 보여주면 충분.
        self._notes = [n for n in (getattr(seg, "example", []) or [])
                       if n["beat_pos"] < self._beats_per_bar]
        self._root = seg.scale_root
        self._note_set = set(seg.note_set)
        self._chord_tones = set(seg.chord_tones())
        self._total_beats = self._beats_per_bar
        self._rel_beat = -1.0
        self.update()

    def set_riff(self, notes, scale_root, note_set, chord_tones,
                 beats_per_bar: int, n_bars: int):
        """원시 리프(상대값) 직접 표시 — 악보 화면의 '스케일 종류당 리프' 미리보기용."""
        self._notes = list(notes or [])
        self._root = scale_root
        self._note_set = set(note_set)
        self._chord_tones = set(chord_tones)
        self._beats_per_bar = max(1, beats_per_bar)
        max_note = max((n["beat_pos"] + n.get("dur_beats", 0.5) for n in self._notes),
                       default=0.0)
        self._total_beats = max(self._beats_per_bar, n_bars * self._beats_per_bar, max_note)
        self._rel_beat = -1.0
        self.update()

    def set_play_pos_sec(self, sec: float, seg_start_sec: float, bpm: float):
        beat_sec = 60.0 / bpm if bpm > 0 else 0.5
        rel = (sec - seg_start_sec) / beat_sec if beat_sec else -1.0
        # 1마디 가이드 안에서 매 마디 순환(반복 구간이어도 헤드가 1마디 안에 머묾, §3)
        if rel >= 0 and self._total_beats > 0:
            rel = rel % self._total_beats
        self._rel_beat = rel
        self.update()

    def clear(self):
        self._notes = []
        self._rel_beat = -1.0
        self.update()

    # ── 렌더 ─────────────────────────────────────────────────────
    def _state(self, pc: int) -> str:
        if pc in self._chord_tones:
            return "CHORD"
        if pc in self._note_set:
            return "SCALE"
        return "OUT"

    def _x(self, beat: float, w: float) -> float:
        return (beat / self._total_beats) * w if self._total_beats else 0.0

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        ruler_h = 16
        lane_y = ruler_h + 2
        lane_h = h - lane_y - 2

        # 배경
        p.setBrush(QColor(T.BG_INSET))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, w, h), 8, 8)

        # 박자 격자 + 눈금 숫자
        f = QFont(T.FONT_MONO); f.setPixelSize(9)
        p.setFont(f)
        total = int(round(self._total_beats))
        for b in range(total + 1):
            x = self._x(b, w)
            is_bar = (b % self._beats_per_bar) == 0
            p.setPen(QPen(QColor(T.BORDER_DEFAULT if is_bar else T.BORDER_SUBTLE),
                          1.4 if is_bar else 0.8))
            p.drawLine(int(x), lane_y, int(x), lane_y + lane_h)
            if b < total:
                p.setPen(QColor(T.TEXT_DIM))
                beat_in_bar = (b % self._beats_per_bar) + 1
                p.drawText(QRectF(x + 2, 0, 24, ruler_h),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           str(beat_in_bar))

        # 비어있으면 안내
        if not self._notes:
            p.setPen(QColor(T.TEXT_MUTED))
            p.setFont(QFont(T.FONT_MONO, 9))
            p.drawText(QRectF(0, lane_y, w, lane_h),
                       Qt.AlignmentFlag.AlignCenter, "리프 없음")
            return

        # 음표 알약
        for n in self._notes:
            bp = n["beat_pos"]
            dur = max(0.25, n.get("dur_beats", 0.5))
            x0 = self._x(bp, w)
            x1 = self._x(bp + dur, w)
            pw = max(16.0, x1 - x0 - 2)
            pc = n["midi"] % 12
            st = self._state(pc)
            active = (self._rel_beat >= bp - 0.05
                      and self._rel_beat < bp + dur + 0.05)
            if st == "CHORD":
                bg = QColor(T.BADGE_ROOT if pc == self._root else T.BADGE_CHORD)
                fg = QColor(T.BADGE_TEXT)
            elif st == "SCALE":
                bg, fg = QColor(T.BADGE_SCALE), QColor(T.BADGE_SCALE_TEXT)
            else:
                bg, fg = QColor(T.BADGE_OUT), QColor(T.BADGE_TEXT)
            pill_h = lane_h * 0.62
            pill_y = lane_y + (lane_h - pill_h) / 2
            rect = QRectF(x0 + 1, pill_y, pw, pill_h)
            p.setBrush(bg)
            p.setPen(QPen(QColor(T.BORDER_ACTIVE), 2) if active else Qt.PenStyle.NoPen)
            p.drawRoundedRect(rect, 6, 6)
            # 스케일 도수 번호
            text = "×" if st == "OUT" else (degree_number(pc, self._root) or "·")
            fn = QFont(T.FONT_MONO); fn.setPixelSize(13); fn.setBold(True)
            p.setFont(fn)
            p.setPen(fg)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        # 재생 헤드
        if 0 <= self._rel_beat <= self._total_beats:
            hx = self._x(self._rel_beat, w)
            p.setPen(QPen(QColor(T.SCRUB_HEAD), 2))
            p.drawLine(int(hx), lane_y - 2, int(hx), lane_y + lane_h + 2)
