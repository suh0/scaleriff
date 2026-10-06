"""피아노 키보드 위젯 — ScaleRiff (SCALERIFF_DESIGN_SPEC §5 v8).

핵심 원칙 (v8):
- 건반 fill·border는 상태와 무관하게 항상 동일 (기본색 고정)
- 상태는 오직 건반 하단 배지(원형 동그라미)만으로 표시 — 당구공처럼
  · 코드톤: 초록 배지 #22c55e  · 스케일음: 회색 배지 #4a4a4a
  · 스케일 밖: 배지 없음 (빈 건반) — 쳤을 때만 건반 전체가 빨간색으로 표시
- 친 건반 (§5.3):
  · 코드톤/스케일음: 배지 유지 + 상태별 컬러 border
  · 스케일 밖: 건반 전체 빨간색 fill (border 없음)
- 범위: 3옥타브 C3–B5 (MIDI 48–83) — 왼손 C3~B3 / 오른손 C4~B5
- 흰 건반 가로:세로 비율 WHITE_RATIO 고정 → 어떤 창에서도 비율 유지(레터박스)
- 배지는 가이드·연습 모드 모두 전체 표시(퀴즈 블러 제거 §10)
- 전환 직전 다음 음의 건반 위 둥근 막대가 넓어지며 예고한다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget, QSizePolicy
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QRectF, pyqtSignal

from gui import theme as T

MIDI_LOW  = 48   # C3
MIDI_HIGH = 83   # B5

WHITE_RATIO = 4.2   # 흰 건반 가로:세로 고정 비율
PREVIEW_SPACE = 10  # 건반 밖 예고 막대를 위한 상단 여백
# 왼손(C3~B3)/오른손(C4~B5) 사이 시각 간격.
GAP_MIDI  = 60       # 이 음(C4) 앞에 간격
GAP_UNITS = 0.8      # 간격 폭(흰 건반 폭 배수)

WHITE_PCS = {0, 2, 4, 5, 7, 9, 11}
BLACK_PCS = {1, 3, 6, 8, 10}


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
        self._split = 0                      # 난이도 목표음 필터(§7.5, 0=없음)
        self._left_targets: set[int] = set()
        self._right_targets: set[int] = set()
        self._preview_notes: set[int] = set()
        self._preview_chords: set[int] = set()
        self._preview_root = 0
        self._preview_opacity = 0.0
        self._preview_progress = 0.0

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

    def set_targets(self, split: int = 0, left=None, right=None):
        """난이도 존별 목표음(pc) — 비목표음 배지는 흐리게(§7.5). split=0이면 해제."""
        self._split = split
        self._left_targets = set(left or ())
        self._right_targets = set(right or ())
        self.update()

    def set_preview(self, notes=(), chords=(), root=0, progress=0.0):
        """다음 음의 왕관 막대: 점점 넓어지고 초반에 빠르게 선명해진다."""
        self._preview_notes = set(notes)
        self._preview_chords = set(chords)
        self._preview_root = root
        t = max(0.0, min(1.0, progress))
        self._preview_progress = t
        self._preview_opacity = 1 - (1 - t) ** 3
        self.update()

    def _draw_preview_crown(self, p: QPainter, midi: int, r: QRectF):
        pc = midi % 12
        if midi in self._pressed or pc not in self._preview_notes or not self._preview_opacity:
            return
        if pc != self._preview_root and pc not in self._preview_chords:
            return
        tint = QColor(T.BADGE_ROOT if pc == self._preview_root else
                      T.BADGE_CHORD)
        tint.setAlphaF(self._preview_opacity)
        p.save()
        p.setBrush(tint)
        p.setPen(Qt.PenStyle.NoPen)
        width = min(14.0, r.width() * 0.5) * (0.3 + 0.7 * self._preview_progress)
        crown = QRectF(r.center().x() - width / 2, r.top() - 8, width, 4)
        p.drawRoundedRect(crown, 2, 2)
        p.restore()

    def _is_dim(self, midi: int) -> bool:
        if not self._split:
            return False
        t = self._left_targets if midi < self._split else self._right_targets
        return (midi % 12) not in t

    # ── 기하: 비율 고정 + 가운데 정렬 ───────────────────────────
    def _geometry(self):
        white_midis = [m for m in range(MIDI_LOW, MIDI_HIGH + 1) if _is_white(m)]
        n = len(white_midis)
        if n == 0:
            return None
        w, h = self.width(), self.height() - PREVIEW_SPACE
        units = n + GAP_UNITS            # 중앙 간격 포함 폭
        kw = w / units
        kh = kw * WHITE_RATIO
        if kh > h:
            kh = h
            kw = kh / WHITE_RATIO
        total_w = kw * units
        return white_midis, (w - total_w) / 2.0, PREVIEW_SPACE + (h - kh) / 2.0, kw, kh

    @staticmethod
    def _wx(i: int, white_midis: list[int], x0: float, kw: float) -> float:
        """i번째 흰 건반의 x — GAP_MIDI 이상이면 중앙 간격만큼 밀림."""
        gap = GAP_UNITS * kw if white_midis[i] >= GAP_MIDI else 0.0
        return x0 + i * kw + gap

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
        """스케일 밖 음인지 여부 — 눌렸을 때 건반 전체 빨간색 표시용."""
        if not self._note_set:
            return False
        pc = midi % 12
        return pc not in self._note_set and pc not in self._chord_tones

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
            rx = self._wx(i, white_midis, x0, kw)
            r = QRectF(rx + 1, y0, kw - 2, kh - 1)
            self._draw_white(p, midi, r)

        # 검은 건반 (흰 건반 위에 덮어 그림) — B|C 경계엔 검은 건반이 없어
        # 중앙 간격과 겹치지 않는다.
        for i, wmidi in enumerate(white_midis):
            if (wmidi % 12) + 1 in BLACK_PCS:
                bmidi = wmidi + 1
                if bmidi > MIDI_HIGH:
                    continue
                rx = self._wx(i, white_midis, x0, kw) + kw - bw / 2
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
                fill = T.KEY_PRESSED_CHORD    # 초록색
            elif cst == "SCALE":
                fill = T.BORDER_DEFAULT       # 회색 (#555555)
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

        self._draw_preview_crown(p, midi, r)

        # 배지 — 눌렸을 때 꽉 찬 색이면 배지 생략, 안 눌렸을 때만 표시
        if cst != "DEFAULT" and not is_pressed:
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
                fill = T.KEY_PRESSED_CHORD    # 초록색
            elif cst == "SCALE":
                fill = T.BORDER_DEFAULT       # 밝은 회색 (#555555)
            else:
                fill = T.KEY_BP_FILL          # 기본 미세 변화
        else:
            fill = T.KEY_B_FILL
        p.setBrush(QColor(fill))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(r, 3, 3)

        self._draw_preview_crown(p, midi, r)

        # 배지 — 안 눌렸을 때만 표시
        if cst != "DEFAULT" and not is_pressed:
            bsz = 20
            cx = r.x() + r.width() / 2
            cy = r.y() + r.height() - bsz / 2 - 3
            self._draw_badge(p, midi, cst, cx, cy, bsz)

    def _draw_badge(self, p: QPainter, midi: int, state: str,
                    cx: float, cy: float, sz: int):
        """원형 배지 (색 동그라미 + 도수 텍스트). CHORD/SCALE만 호출됨."""
        pc = midi % 12
        deg = self._degrees.get(pc)
        if deg is None:
            return
        if self._is_dim(midi):
            p.setOpacity(0.25)

        if state == "CHORD":
            bg = QColor(T.BADGE_ROOT if deg == "1" else T.BADGE_CHORD)  # 근음=파랑
            fg = QColor(T.BADGE_TEXT)
        else:   # SCALE
            bg = QColor(T.BADGE_SCALE)
            fg = QColor(T.BADGE_SCALE_TEXT)

        badge = QRectF(cx - sz / 2, cy - sz / 2, sz, sz)
        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(badge)

        f = QFont(T.FONT_MONO)
        f.setPixelSize(max(7, int(sz * 0.46)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(fg)
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, deg)
        p.setOpacity(1.0)

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
                    bx = self._wx(i, white_midis, x0, kw) + kw - bw / 2
                    if bx <= mx <= bx + bw:
                        return bmidi
        for i in range(len(white_midis)):    # 중앙 간격 클릭은 None
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
