"""리프 피아노롤 — 세로 건반(왼쪽 90° 회전) + 음높이별 리프 노트.

왼쪽 거터 = 오른손 2옥타브(도~시 = midi 60~83 고정) 세로 건반. 흰건반은 흑건
중점까지 확장돼 실제 피아노 모양, 스케일 도수 배지를 각 건반 중앙에 표시(코드톤
초록·근음 파랑·스케일음 회색). 오른쪽은 박자 격자 위 균등 세미톤 y로 노트 알약.

리프는 ml/representation.decode가 60~83(C4~B5)만 생성 — 여기선 표시만.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QRectF

from analyze.theory import degree_number
from gui import theme as T

WHITE_PCS = {0, 2, 4, 5, 7, 9, 11}
LO, HI = 60, 83   # 도~시 2옥타브(생성 음역과 동일, ml/representation.decode)
GUTTER = 56       # 세로 건반 폭
SEMI_H = 12       # 건반 한 칸 높이(모든 건반 동일 — 균등 세미톤)
RULER_H = 16      # 상단 박자 눈금


class RiffRoll(QWidget):
    """스케일 종류당 리프(C 기준, root=0)를 피아노롤로 표시."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._notes: list[dict] = []
        self._note_set: set[int] = set()
        self._chord_tones: set[int] = set()
        self._root = 0
        self._beats_per_bar = 4
        self._total_beats = 4.0
        self._lo, self._hi = LO, HI
        self.setFixedHeight(self._lanes() * SEMI_H + RULER_H + 4)

    def _lanes(self) -> int:
        return self._hi - self._lo + 1

    def set_riff(self, notes, note_set, chord_tones,
                 beats_per_bar: int, n_bars: int, root: int = 0):
        self._notes = list(notes or [])
        self._root = root
        self._note_set = set(note_set)
        self._chord_tones = set(chord_tones)
        self._beats_per_bar = max(1, beats_per_bar)
        max_note = max((n["beat_pos"] + n.get("dur_beats", 0.5) for n in self._notes),
                       default=0.0)
        self._total_beats = max(self._beats_per_bar,
                                n_bars * self._beats_per_bar, max_note)
        self.update()

    def clear(self):
        self._notes = []
        self.update()

    # ── 좌표 ─────────────────────────────────────────────────────
    def _x(self, beat: float) -> float:
        return GUTTER + (beat / self._total_beats) * (self.width() - GUTTER)

    def _y(self, midi: int) -> float:
        """세미톤 균등 y(중심) — 위가 고음."""
        return RULER_H + (self._hi - midi) * SEMI_H + SEMI_H / 2

    def _state(self, pc: int) -> str:
        if pc in self._chord_tones:
            return "CHORD"
        if pc in self._note_set:
            return "SCALE"
        return "OUT"

    def _fill(self, pc: int) -> QColor:
        """상태색 — 코드톤 중 근음(도수 1)은 파랑, 나머지 코드톤 초록."""
        st = self._state(pc)
        if st == "CHORD":
            return QColor(T.BADGE_ROOT if pc == self._root else T.BADGE_CHORD)
        return QColor(T.BADGE_SCALE if st == "SCALE" else T.BADGE_OUT)

    def _badge(self, p: QPainter, pc: int, r: QRectF, font: QFont):
        """스케일 안 건반 정중앙에 도수 배지. OUT는 안 그림."""
        st = self._state(pc)
        if st == "OUT":
            return
        fg = QColor(T.BADGE_TEXT if st == "CHORD" else T.BADGE_SCALE_TEXT)
        p.setBrush(self._fill(pc))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(r)
        text = degree_number(pc, self._root)
        if text:
            p.setFont(font)
            p.setPen(fg)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    # ── 렌더 ─────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        p.setBrush(QColor(T.BG_INSET))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(0, 0, w, self.height()), 8, 8)

        badge_f = QFont(T.FONT_MONO)
        badge_f.setPixelSize(8)
        badge_f.setBold(True)
        bsz = SEMI_H - 1        # 배지 지름(건반 칸 안)

        # ── 건반 이미지(실제 피아노) — 흰건반은 흑건 중점까지 확장돼
        #    흑건이 흰건반을 반반으로 나눔. 노트 그리드(오른쪽)는 균등 세미톤. ──
        bk_w = GUTTER * 0.6      # 흑건 길이(짧게 — 앞쪽은 흰건반)
        for midi in range(self._lo, self._hi + 1):   # 흰건반 먼저
            if midi % 12 not in WHITE_PCS:
                continue
            top = self._y(midi) - SEMI_H / 2
            bot = top + SEMI_H
            if (midi + 1) % 12 not in WHITE_PCS:   # 위 이웃이 흑건 → 중점까지
                top -= SEMI_H / 2
            if (midi - 1) % 12 not in WHITE_PCS:   # 아래 이웃이 흑건 → 중점까지
                bot += SEMI_H / 2
            p.setBrush(QColor(T.KEY_W_FILL))
            p.setPen(QPen(QColor(T.KEY_W_BORDER), 1.0))
            p.drawRect(QRectF(0, top, GUTTER, bot - top))
        for midi in range(self._lo, self._hi + 1):   # 흑건(짧게, 세미톤 중심)
            if midi % 12 in WHITE_PCS:
                continue
            cy = self._y(midi)
            p.setBrush(QColor(T.KEY_B_FILL))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRect(QRectF(0, cy - SEMI_H / 2, bk_w, SEMI_H))

        # ── 롤 가로선 가이드: 매 세미톤 경계(거터 오른쪽만 — 그리드 유지) ──
        for midi in range(self._lo, self._hi + 2):
            y = self._y(midi) - SEMI_H / 2 if midi <= self._hi \
                else self._y(self._hi) + SEMI_H / 2
            octave = (midi % 12 == 0)      # C 경계만 진하게
            p.setPen(QPen(QColor(T.BORDER_DEFAULT if octave else T.BORDER_SUBTLE),
                          1 if octave else 0.6))
            p.drawLine(int(GUTTER), int(y), int(w), int(y))

        # ── 스케일 배지(각 건반 중앙) — 흰건반은 앞쪽(흑건 없는 영역) ──
        for midi in range(self._lo, self._hi + 1):
            cy = self._y(midi)
            cx = (GUTTER + bk_w) / 2 if midi % 12 in WHITE_PCS else bk_w / 2
            r = QRectF(cx - bsz / 2, cy - bsz / 2, bsz, bsz)
            self._badge(p, midi % 12, r, badge_f)

        # ── 박자 격자 + 눈금 ──
        f = QFont(T.FONT_MONO)
        f.setPixelSize(9)
        p.setFont(f)
        total = int(round(self._total_beats))
        for b in range(total + 1):
            x = self._x(b)
            is_bar = (b % self._beats_per_bar) == 0
            p.setPen(QPen(QColor(T.BORDER_DEFAULT if is_bar else T.BORDER_SUBTLE),
                          1.4 if is_bar else 0.8))
            p.drawLine(int(x), RULER_H, int(x), self.height() - 2)
            if b < total:
                p.setPen(QColor(T.TEXT_DIM))
                p.drawText(QRectF(x + 2, 0, 24, RULER_H),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           str((b % self._beats_per_bar) + 1))

        if not self._notes:
            p.setPen(QColor(T.TEXT_MUTED))
            p.setFont(QFont(T.FONT_MONO, 9))
            p.drawText(QRectF(GUTTER, RULER_H, w - GUTTER,
                              self.height() - RULER_H),
                       Qt.AlignmentFlag.AlignCenter, "리프 없음")
            return

        # ── 노트 알약 — 음높이 y에 배치(도수는 거터가 보여주므로 무라벨) ──
        ph = SEMI_H * 1.2
        for n in self._notes:
            bp = n["beat_pos"]
            dur = max(0.25, n.get("dur_beats", 0.5))
            x0, x1 = self._x(bp), self._x(bp + dur)
            p.setBrush(self._fill(n["midi"] % 12))
            p.setPen(QPen(QColor(T.BG_INSET), 1))
            p.drawRoundedRect(
                QRectF(x0 + 1, self._y(n["midi"]) - ph / 2,
                       max(8.0, x1 - x0 - 2), ph), 3, 3)
