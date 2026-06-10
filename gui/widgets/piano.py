"""피아노 키보드 위젯 — ScaleRiff (SCALERIFF_DESIGN_SPEC §5 v4).

- 범위: 2옥타브(C4–B5, MIDI 60~83).
- 흰건반 가로:세로 비율(WHITE_RATIO) 고정 → 어떤 창에서도 비율 유지(레터박스).
- 상태색: 코드톤=초록 테두리, 스케일밖=빨강 테두리, 기본=회색(theme.KW/KB v4).
- 친 건반: 흰 글로우 링(§5.3) + '●' 라벨.
- 기능 라벨(도수)은 코드톤·스케일음 위에 표시(§5).
- 모드(§5.4): guide=전체 표시 / quiz=가림(기본색)→친 건반만 해제, 코드 바뀌면 리셋.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QRectF, pyqtSignal

from gui import theme as T

MIDI_LOW = 60    # C4
MIDI_HIGH = 83   # B5 (2옥타브)

WHITE_RATIO = 4.2

WHITE_PCS = [0, 2, 4, 5, 7, 9, 11]
BLACK_PCS = [1, 3, 6, 8, 10]


def _is_white(midi: int) -> bool:
    return (midi % 12) in WHITE_PCS


class PianoWidget(QWidget):
    notePlayed = pyqtSignal(int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._mouse_midi = None
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
        self._degrees = dict(degrees or {})
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
    def _state(self, midi: int) -> str:
        if midi in self._pressed:
            return "PRESSED"
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

    # ── 렌더 ─────────────────────────────────────────────────────
    def paintEvent(self, event):
        geo = self._geometry()
        if geo is None:
            return
        white_midis, x0, y0, kw, kh = geo
        black_w = kw * 0.6
        black_h = kh * 0.62
        lh = max(13, kh * 0.13)
        f = QFont(T.FONT_MONO); f.setPointSize(max(8, int(kw * 0.17))); f.setBold(True)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        pressed_rects = []   # 글로우는 모든 키 그린 뒤 위에 덧그림

        # 흰건반
        for i, midi in enumerate(white_midis):
            x = x0 + i * kw
            r = QRectF(x + 1, y0, kw - 2, kh - 1)
            st = self._state(midi)
            fill, border, txt, bw = T.KW[st]
            p.fillRect(r, QColor(fill))
            if border:
                p.setPen(QPen(QColor(border), bw))
                p.drawRoundedRect(r, 3, 3)
            label = "●" if st == "PRESSED" else None
            self._draw_degree(p, f, midi, txt,
                              QRectF(x + 1, y0 + kh - lh - 6, kw - 2, lh), label)
            if st == "PRESSED":
                pressed_rects.append(r)

        # 검은건반
        for i, wmidi in enumerate(white_midis):
            if (wmidi % 12) + 1 in BLACK_PCS:
                bmidi = wmidi + 1
                if bmidi > MIDI_HIGH:
                    continue
                x = x0 + (i + 1) * kw - black_w / 2
                r = QRectF(x, y0, black_w, black_h)
                st = self._state(bmidi)
                fill, border, txt, bw = T.KB[st]
                p.fillRect(r, QColor(fill))
                if border:
                    p.setPen(QPen(QColor(border), bw))
                    p.drawRoundedRect(r, 3, 3)
                label = "●" if st == "PRESSED" else None
                self._draw_degree(p, f, bmidi, txt,
                                  QRectF(x, y0 + black_h - lh - 4, black_w, lh), label)
                if st == "PRESSED":
                    pressed_rects.append(r)

        # 친 건반 글로우(§5.3): 배경 갭 → 흰 링 → 발광
        for r in pressed_rects:
            p.setBrush(Qt.BrushStyle.NoBrush)
            # 배경색 갭 (2px)
            p.setPen(QPen(QColor(T.BG_BASE), 4))
            p.drawRoundedRect(r.adjusted(-1, -1, 1, 1), 4, 4)
            # 흰 링
            p.setPen(QPen(QColor(T.GLOW), 2.5))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
            # 외곽 발광 (반투명)
            p.setPen(QPen(QColor(255, 255, 255, 60), 6))
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 5, 5)

    def _draw_degree(self, p, f, midi, txt_col, rect, override: str | None = None):
        """도수 라벨 또는 override 텍스트를 건반 아래에 그린다."""
        pc = midi % 12
        if txt_col is None:
            return
        text = override if override is not None else self._degrees.get(pc)
        if text is None:
            return
        p.setFont(f)
        p.setPen(QColor(txt_col))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    # ── 마우스 입력 ──────────────────────────────────────────────
    def _midi_at(self, mx: float, my: float) -> int | None:
        geo = self._geometry()
        if geo is None:
            return None
        white_midis, x0, y0, kw, kh = geo
        black_w = kw * 0.6
        black_h = kh * 0.62
        if my < y0 or my > y0 + kh:
            return None
        if my <= y0 + black_h:
            for i, wmidi in enumerate(white_midis):
                if (wmidi % 12) + 1 in BLACK_PCS:
                    bmidi = wmidi + 1
                    if bmidi > MIDI_HIGH:
                        continue
                    bx = x0 + (i + 1) * kw - black_w / 2
                    if bx <= mx <= bx + black_w:
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
