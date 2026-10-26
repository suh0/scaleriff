"""피아노 키보드 위젯 — ScaleRiff.

핵심 원칙 (v8):
- 건반 fill·border는 상태와 무관하게 항상 동일 (기본색 고정)
- 상태는 오직 건반 하단 배지(원형 동그라미)만으로 표시 — 당구공처럼
  · 코드톤: 초록 배지 #22c55e  · 스케일음: 회색 배지 #4a4a4a
  · 스케일 밖: 배지 없음 (빈 건반) — 쳤을 때만 건반 전체가 빨간색으로 표시
- 친 건반 (§5.3):
  · 코드톤/스케일음: 배지 유지 + 상태별 컬러 border
  · 스케일 밖: 건반 전체 빨간색 fill (border 없음)
- 범위: 오른손 2옥타브 C4–B5 (MIDI 60–83) — 리프 생성 음역과 동일
- 흰 건반 가로:세로 비율 WHITE_RATIO 고정 → 어떤 창에서도 비율 유지(레터박스)
- 배지는 가이드·연습 모드 모두 전체 표시(퀴즈 블러 제거 §10)
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtCore import Qt, QRectF, pyqtSignal

from gui import theme as T

MIDI_LOW  = 60   # C4
MIDI_HIGH = 83   # B5

WHITE_RATIO = 4.2   # 흰 건반 가로:세로 고정 비율
PREVIEW_SPACE = 16  # 흰 건반 아래 여백(구 예고 막대 자리 — 기하 유지)
PREVIEW_HEIGHT = 4

WHITE_PCS = {0, 2, 4, 5, 7, 9, 11}
BLACK_PCS = {1, 3, 6, 8, 10}

# 실제 건반 비율: 흑건 13.7/23.5mm 폭, 95/150mm 길이.
# 흑건은 경계 가운데가 아니다 — C~E는 5등분, F~B는 7등분 자리(C#·F# 왼쪽, D#·A# 오른쪽, G# 가운데).
BLACK_W = 0.58
BLACK_L = 0.63
BLACK_OFFSET = {1: -0.1, 3: 0.1, 6: -1 / 7, 8: 0.0, 10: 1 / 7}   # 경계 대비 흰 건반 폭 비율


def _is_white(midi: int) -> bool:
    return (midi % 12) in WHITE_PCS


def black_x(boundary: float, kw: float, midi: int) -> float:
    """흑건 왼쪽 x — boundary = 바로 왼쪽 흰 건반의 오른쪽 경계."""
    return boundary - kw * BLACK_W / 2 + BLACK_OFFSET[midi % 12] * kw


class PianoWidget(QWidget):
    notePlayed = pyqtSignal(int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._mouse_midi: int | None = None
        self._note_set: set[int] = set()
        self._chord_tones: set[int] = set()
        self._degrees: dict[int, str] = {}   # pc → 곡 스케일 주음 기준 번호(곡 내내 고정)
        self._chord_root: int | None = None  # 지금 코드의 근음 pc(코드 없는 구간은 None)
        self._pressed: set[int] = set()

    # ── 상태 세터 ────────────────────────────────────────────────
    def set_scale(self, note_set, chord_tones, chord_root=None):
        self._note_set = set(note_set) if note_set else set()
        self._chord_tones = set(chord_tones) if chord_tones else set()
        self._chord_root = chord_root
        self.update()

    def set_degrees(self, degrees: dict):
        self._degrees = {pc: str(v) for pc, v in (degrees or {}).items()}
        self.update()

    def set_pressed(self, pressed):
        self._pressed = set(pressed)
        self.update()

    # ── 기하: 비율 고정 + 가운데 정렬 ───────────────────────────
    def _geometry(self):
        white_midis = [m for m in range(MIDI_LOW, MIDI_HIGH + 1) if _is_white(m)]
        n = len(white_midis)
        if n == 0:
            return None
        w, h = self.width(), self.height() - PREVIEW_SPACE
        kw = w / n
        kh = kw * WHITE_RATIO
        if kh > h:
            kh = h
            kw = kh / WHITE_RATIO
        total_w = kw * n
        return white_midis, (w - total_w) / 2.0, (h - kh) / 2.0, kw, kh

    @staticmethod
    def _wx(i: int, white_midis: list[int], x0: float, kw: float) -> float:
        """i번째 흰 건반의 x."""
        return x0 + i * kw

    # ── 상태 판정 ────────────────────────────────────────────────
    def _content_state(self, midi: int) -> str:
        """press 무관 스케일/코드 상태 — 배지·border 색 결정용.

        OUT은 배지를 표시하지 않으므로 DEFAULT로 반환.
        스케일 밖 눌림 여부는 _is_out()로 별도 판정.
        """
        if not self._note_set:
            return "DEFAULT"
        pc = midi % 12
        if pc in self._chord_tones:
            return "CHORD"
        if pc in self._note_set:
            return "SCALE"
        return "DEFAULT"   # OUT → 배지 없음, 빈 건반으로 표시

    def _is_out(self, midi: int) -> bool:
        """스케일 밖 음인지 여부 — 눌렸을 때 건반 전체 빨간색 표시용(지금 코드 근음은 제외)."""
        if not self._note_set:
            return False
        pc = midi % 12
        return pc not in self._note_set and pc not in self._chord_tones and pc != self._chord_root

    # ── 렌더 ─────────────────────────────────────────────────────
    def paintEvent(self, event):
        geo = self._geometry()
        if geo is None:
            return
        white_midis, x0, y0, kw, kh = geo
        bw = kw * BLACK_W
        bh = kh * BLACK_L

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 흰 건반
        for i, midi in enumerate(white_midis):
            rx = self._wx(i, white_midis, x0, kw)
            r = QRectF(rx + 1, y0, kw - 2, kh - 1)
            self._draw_white(p, midi, r)

        # 검은 건반 (흰 건반 위에 덮어 그림)
        for i, wmidi in enumerate(white_midis):
            if (wmidi % 12) + 1 in BLACK_PCS:
                bmidi = wmidi + 1
                if bmidi > MIDI_HIGH:
                    continue
                rx = black_x(self._wx(i, white_midis, x0, kw) + kw, kw, bmidi)
                r = QRectF(rx, y0, bw, bh)
                self._draw_black(p, bmidi, r)

    def _draw_white(self, p: QPainter, midi: int, r: QRectF):
        is_pressed = midi in self._pressed
        cst = self._content_state(midi)
        is_out_pressed = is_pressed and self._is_out(midi)

        # fill — 눌렸을 때 상태별 전체 색 채우기
        if is_pressed:
            if is_out_pressed:
                fill = T.KEY_PRESSED_OUT      # 빨간색
            elif cst == "CHORD":
                fill = (T.BADGE_ROOT if self._degrees.get(midi % 12) == "1"
                        else T.KEY_PRESSED_CHORD)
            elif cst == "SCALE":
                fill = T.KEY_SCALE_PRESSED_FILL
            else:
                fill = T.KEY_WP_FILL          # 기본 미세 변화
        else:
            fill = T.KEY_W_FILL
        p.setBrush(QColor(fill))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 3, 3)

        # 기본 border — 꽉 찬 색 상태에서는 생략
        if not is_pressed or cst == "DEFAULT":
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(T.KEY_W_BORDER), 1.0))
            p.drawRoundedRect(r, 3, 3)

        # 배지는 눌림 상태에도 유지한다.
        if cst != "DEFAULT":
            bsz = 26
            cx = r.x() + r.width() / 2
            cy = r.y() + r.height() - bsz / 2 - 5
            self._draw_badge(p, midi, cst, cx, cy, bsz)

    def _draw_black(self, p: QPainter, midi: int, r: QRectF):
        is_pressed = midi in self._pressed
        cst = self._content_state(midi)
        is_out_pressed = is_pressed and self._is_out(midi)

        # fill — 검은 건반 눌렸을 때 상태별 색
        if is_pressed:
            if is_out_pressed:
                fill = T.KEY_PRESSED_OUT      # 빨간색
            elif cst == "CHORD":
                fill = (T.BADGE_ROOT if self._degrees.get(midi % 12) == "1"
                        else T.KEY_PRESSED_CHORD)
            elif cst == "SCALE":
                fill = T.KEY_SCALE_PRESSED_FILL
            else:
                fill = T.KEY_BP_FILL          # 기본 미세 변화
        else:
            fill = T.KEY_B_FILL
        p.setBrush(QColor(fill))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 3, 3)

        # 하단 예고 막대 높이만큼 배지를 올려 겹침을 피한다.
        if cst != "DEFAULT":
            bsz = 20
            cx = r.x() + r.width() / 2
            cy = r.y() + r.height() - bsz / 2 - 3 - PREVIEW_HEIGHT
            self._draw_badge(p, midi, cst, cx, cy, bsz)

    def _draw_badge(self, p: QPainter, midi: int, state: str,
                    cx: float, cy: float, sz: int):
        """숫자 없는 원형 색 배지. CHORD/SCALE만 호출됨."""
        pc = midi % 12
        deg = self._degrees.get(pc)
        if deg is None:
            return

        if state == "CHORD":
            bg = QColor(T.BADGE_ROOT if deg == "1" else T.BADGE_CHORD)  # 근음=파랑
            if deg != "1":
                sz *= 0.85
        else:   # SCALE
            bg = QColor(T.BADGE_SCALE)
            sz *= 0.70

        badge = QRectF(cx - sz / 2, cy - sz / 2, sz, sz)
        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(badge)

    # ── 마우스 입력 ──────────────────────────────────────────────
    def _midi_at(self, mx: float, my: float) -> int | None:
        geo = self._geometry()
        if geo is None:
            return None
        white_midis, x0, y0, kw, kh = geo
        bw = kw * BLACK_W
        bh = kh * BLACK_L
        if my < y0 or my > y0 + kh:
            return None
        if my <= y0 + bh:
            for i, wmidi in enumerate(white_midis):
                if (wmidi % 12) + 1 in BLACK_PCS:
                    bmidi = wmidi + 1
                    if bmidi > MIDI_HIGH:
                        continue
                    bx = black_x(self._wx(i, white_midis, x0, kw) + kw, kw, bmidi)
                    if bx <= mx <= bx + bw:
                        return bmidi
        for i in range(len(white_midis)):
            wx = self._wx(i, white_midis, x0, kw)
            if wx <= mx < wx + kw:
                return white_midis[i]
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
