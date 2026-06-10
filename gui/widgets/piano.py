"""피아노 키보드 위젯 — ScaleRiff (SCALERIFF_DESIGN_SPEC §5 v5/v6 배지 시스템).

핵심 원칙 (v5/v6):
- 건반 fill·border는 상태와 무관하게 항상 동일 (기본색 고정)
- 상태는 오직 건반 하단 배지(원형 동그라미)만으로 표시 — 당구공처럼
  · 코드톤: 초록 배지 #22c55e  · 스케일음: 회색 배지 #4a4a4a  · 밖: 빨강 배지 #ef4444
- 친 건반 (§5.3): 배지 유지 + 상태별 컬러 border 추가 (초록/회색/빨강)
- 범위: 2옥타브 C4–B5 (MIDI 60–83)
- 흰 건반 가로:세로 비율 WHITE_RATIO 고정 → 어떤 창에서도 비율 유지(레터박스)
- 모드 (§5.4): guide=전체 배지 / quiz=숨김→친 건반만 공개
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QRectF, pyqtSignal

from gui import theme as T

MIDI_LOW  = 60   # C4
MIDI_HIGH = 83   # B5

WHITE_RATIO = 4.2   # 흰 건반 가로:세로 고정 비율

WHITE_PCS = {0, 2, 4, 5, 7, 9, 11}
BLACK_PCS = {1, 3, 6, 8, 10}

# 친 건반 상태별 border: (색, 두께)
_PRESSED_BORDER: dict[str, tuple[str, float]] = {
    "CHORD":   (T.KEY_PRESSED_CHORD, 2.5),
    "SCALE":   (T.KEY_PRESSED_SCALE, 2.5),
    "OUT":     (T.KEY_PRESSED_OUT,   2.5),
    "DEFAULT": (T.BORDER_DEFAULT,    1.5),
}
_PRESSED_BORDER_BK: dict[str, tuple[str, float]] = {
    "CHORD":   (T.KEY_PRESSED_CHORD, 2.0),
    "SCALE":   (T.KEY_PRESSED_SCALE, 2.0),
    "OUT":     (T.KEY_PRESSED_OUT,   2.0),
    "DEFAULT": (T.BORDER_DEFAULT,    1.0),
}


def _is_white(midi: int) -> bool:
    return (midi % 12) in WHITE_PCS


class PianoWidget(QWidget):
    notePlayed = pyqtSignal(int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._mouse_midi: int | None = None
        self._note_set: set[int] = set()
        self._chord_tones: set[int] = set()
        self._degrees: dict[int, str] = {}
        self._pressed: set[int] = set()
        self._mode = "guide"
        self._revealed: set[int] = set()

    # ── 상태 세터 ────────────────────────────────────────────────
    def set_scale(self, note_set, chord_tones):
        self._note_set = set(note_set) if note_set else set()
        self._chord_tones = set(chord_tones) if chord_tones else set()
        self.update()

    def set_degrees(self, degrees: dict):
        self._degrees = {pc: str(v) for pc, v in (degrees or {}).items()}
        self.update()

    def set_pressed(self, pressed):
        self._pressed = set(pressed)
        self.update()

    def set_mode(self, mode: str):
        self._mode = "quiz" if mode == "quiz" else "guide"
        self.update()

    def reveal(self, midi: int):
        self._revealed.add(midi)
        self.update()

    def clear_reveal(self):
        self._revealed.clear()
        self.update()

    # ── 기하: 비율 고정 + 가운데 정렬 ───────────────────────────
    def _geometry(self):
        white_midis = [m for m in range(MIDI_LOW, MIDI_HIGH + 1) if _is_white(m)]
        n = len(white_midis)
        if n == 0:
            return None
        w, h = self.width(), self.height()
        kw = w / n
        kh = kw * WHITE_RATIO
        if kh > h:
            kh = h
            kw = kh / WHITE_RATIO
        total_w = kw * n
        return white_midis, (w - total_w) / 2.0, (h - kh) / 2.0, kw, kh

    # ── 상태 판정 ────────────────────────────────────────────────
    def _content_state(self, midi: int) -> str:
        """press 무관 스케일/코드 상태 — 배지·border 색 결정용."""
        if not self._note_set:
            return "DEFAULT"
        if self._mode == "quiz" and midi not in self._revealed:
            return "DEFAULT"
        pc = midi % 12
        if pc in self._chord_tones:
            return "CHORD"
        if pc in self._note_set:
            return "SCALE"
        return "OUT"

    def _should_show_badge(self, midi: int) -> bool:
        """배지를 그려야 하면 True (친 건반 포함 — 배지는 항상 유지)."""
        cst = self._content_state(midi)
        return cst != "DEFAULT"

    # ── 렌더 ─────────────────────────────────────────────────────
    def paintEvent(self, event):
        geo = self._geometry()
        if geo is None:
            return
        white_midis, x0, y0, kw, kh = geo
        bw = kw * 0.6     # 검은 건반 너비
        bh = kh * 0.62    # 검은 건반 높이

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 흰 건반
        for i, midi in enumerate(white_midis):
            rx = x0 + i * kw
            r = QRectF(rx + 1, y0, kw - 2, kh - 1)
            self._draw_white(p, midi, r)

        # 검은 건반 (흰 건반 위에 덮어 그림)
        for i, wmidi in enumerate(white_midis):
            if (wmidi % 12) + 1 in BLACK_PCS:
                bmidi = wmidi + 1
                if bmidi > MIDI_HIGH:
                    continue
                rx = x0 + (i + 1) * kw - bw / 2
                r = QRectF(rx, y0, bw, bh)
                self._draw_black(p, bmidi, r)

    def _draw_white(self, p: QPainter, midi: int, r: QRectF):
        is_pressed = midi in self._pressed
        cst = self._content_state(midi)

        # fill (항상 고정, 친 건반만 미세 변화)
        p.setBrush(QColor(T.KEY_WP_FILL if is_pressed else T.KEY_W_FILL))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 3, 3)

        # 기본 border
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(T.KEY_W_BORDER), 1.0))
        p.drawRoundedRect(r, 3, 3)

        # 친 건반 상태 border
        if is_pressed:
            col, lw = _PRESSED_BORDER.get(cst, _PRESSED_BORDER["DEFAULT"])
            p.setPen(QPen(QColor(col), lw))
            p.drawRoundedRect(r, 3, 3)

        # 배지 (친 건반 포함 항상 표시)
        if cst != "DEFAULT":
            bsz = 26
            cx = r.x() + r.width() / 2
            cy = r.y() + r.height() - bsz / 2 - 5
            self._draw_badge(p, midi, cst, cx, cy, bsz)

    def _draw_black(self, p: QPainter, midi: int, r: QRectF):
        is_pressed = midi in self._pressed
        cst = self._content_state(midi)

        # fill
        p.setBrush(QColor(T.KEY_BP_FILL if is_pressed else T.KEY_B_FILL))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 3, 3)

        # 친 건반 상태 border
        if is_pressed:
            col, lw = _PRESSED_BORDER_BK.get(cst, _PRESSED_BORDER_BK["DEFAULT"])
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(col), lw))
            p.drawRoundedRect(r, 3, 3)

        # 배지 (친 건반 포함 항상 표시)
        if cst != "DEFAULT":
            bsz = 20
            cx = r.x() + r.width() / 2
            cy = r.y() + r.height() - bsz / 2 - 3
            self._draw_badge(p, midi, cst, cx, cy, bsz)

    def _draw_badge(self, p: QPainter, midi: int, state: str,
                    cx: float, cy: float, sz: int):
        """원형 배지 (색 동그라미 + 도수 텍스트)."""
        pc = midi % 12
        deg = self._degrees.get(pc)
        text = "×" if state == "OUT" else (deg if deg is not None else None)
        if text is None:
            return

        if state == "CHORD":
            bg = QColor(T.BADGE_CHORD)
            fg = QColor(T.BADGE_TEXT)
        elif state == "SCALE":
            bg = QColor(T.BADGE_SCALE)
            fg = QColor(T.BADGE_SCALE_TEXT)
        else:   # OUT
            bg = QColor(T.BADGE_OUT)
            fg = QColor(T.BADGE_TEXT)

        badge = QRectF(cx - sz / 2, cy - sz / 2, sz, sz)
        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(badge)

        f = QFont(T.FONT_MONO)
        f.setPixelSize(max(7, int(sz * 0.46)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(fg)
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    # ── 마우스 입력 ──────────────────────────────────────────────
    def _midi_at(self, mx: float, my: float) -> int | None:
        geo = self._geometry()
        if geo is None:
            return None
        white_midis, x0, y0, kw, kh = geo
        bw = kw * 0.6
        bh = kh * 0.62
        if my < y0 or my > y0 + kh:
            return None
        if my <= y0 + bh:
            for i, wmidi in enumerate(white_midis):
                if (wmidi % 12) + 1 in BLACK_PCS:
                    bmidi = wmidi + 1
                    if bmidi > MIDI_HIGH:
                        continue
                    bx = x0 + (i + 1) * kw - bw / 2
                    if bx <= mx <= bx + bw:
                        return bmidi
        idx = int((mx - x0) // kw)
        if 0 <= idx < len(white_midis):
            return white_midis[idx]
        return None

    def mousePressEvent(self, e):
        midi = self._midi_at(e.position().x(), e.position().y())
        if midi is not None:
            self._mouse_midi = midi
            self.notePlayed.emit(midi, True)

    def mouseReleaseEvent(self, e):
        if self._mouse_midi is not None:
            self.notePlayed.emit(self._mouse_midi, False)
            self._mouse_midi = None


if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    from analyze.theory import parse_chord, degree_number
    app = QApplication(sys.argv)
    pw = PianoWidget()
    ch = parse_chord("G7")
    ns = [0, 2, 4, 5, 7, 9, 11]
    pw.set_scale(ns, ch.chord_tones())
    pw.set_degrees({pc: degree_number(pc, ch.root) for pc in ns})
    pw.set_pressed({67})
    pw.resize(820, 240)
    pw.show()
    sys.exit(app.exec())
