"""모니터박스 — 현재/다음 코드 표시 + (리프모드) 리프 음표를 해당 건반으로 떨어뜨리는 예고."""
import bisect
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QLinearGradient, QFont
from PyQt6.QtWidgets import QWidget

from gui import theme as T
from gui.widgets.piano import MIDI_LOW, MIDI_HIGH, _is_white


class FallingNotes(QWidget):
    def __init__(self, piano, parent=None):
        super().__init__(parent)
        self.piano = piano
        self._events = []
        self._sec = 0.0
        self._lead = 1.0
        self._beat = .5
        self._beat_grid = []
        self._loops = []
        self.show_notes = False            # 리프모드에서만 노드 낙하
        self._chords = ("", "", "", "", 0.0, 1.0)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_chords(self, cur, kind, nxt, prev, grow, push):
        """cur/kind=현재 코드·스케일, nxt=다음 코드, prev=방금 밀려나는 코드.
        grow 0→1: 다음 코드가 커짐 · push 0→1: 바뀐 직후 새 코드가 내려오며 prev를 밀어냄."""
        self._chords = (cur, kind, nxt, prev, grow, push)
        self.update()

    def _draw_chords(self, p):
        cur, kind, nxt, prev, grow, push = self._chords
        h, w = self.height(), self.width()
        big = max(28.0, min(96.0, h * 0.32))
        mid_y, top_y = h * 0.5, h * 0.16
        ease = 1 - (1 - push) ** 3

        def text(name, size, y, alpha):
            if not name or size < 1 or alpha <= 0:
                return
            f = QFont(T.FONT_SANS_EN)
            f.setBold(True)
            f.setPixelSize(int(size))
            p.setFont(f)
            c = QColor(T.TEXT_PRIMARY)
            c.setAlphaF(alpha)
            p.setPen(c)
            p.drawText(QRectF(0, y - size, w, size * 2), Qt.AlignmentFlag.AlignCenter, name)

        small = big * (0.4 + 0.25 * grow)
        # 밀려나는 이전 코드: 중앙 → 아래로, 페이드
        text(prev, big, mid_y + (h - mid_y) * ease, 0.35 * (1 - ease))
        # 현재 코드: 다음 코드 자리(위·작게) → 중앙·크게
        size = small + (big - small) * ease if prev else big
        y = top_y + (mid_y - top_y) * ease if prev else mid_y
        text(cur, size, y, 0.2 + 0.15 * ease if prev else 0.35)
        if kind and ease >= 1:
            text(kind, big * 0.18, mid_y + big * 0.62, 0.3)
        # 다음 코드: 위에서 작게 → 점점 커짐(push 동안엔 숨김)
        if ease >= 1:
            text(nxt, small, top_y, 0.2)

    def set_events(self, events, beat_sec, beat_grid=()):
        self._events = events
        self._lead = 4 * beat_sec
        self._beat = beat_sec
        self._beat_grid = list(beat_grid)
        self.update()

    def set_position(self, sec, loops=()):
        self._sec = sec
        self._loops = loops
        self.update()

    def _beat_lines(self):
        if self._lead <= 0 or self._beat <= 0:
            return []
        loop = next(((start, end) for start, end in self._loops
                     if start <= self._sec < end), None)
        grid = self._beat_grid
        if not grid:
            first = int(self._sec // self._beat)
            times = [(first + i) * self._beat for i in range(6)]
        elif loop:
            start, end = loop
            length = end - start
            times = []
            for when in grid[bisect.bisect_left(grid, start):bisect.bisect_left(grid, end)]:
                when += max(0, int((self._sec - when) // length)) * length
                while when <= self._sec + self._lead:
                    if when >= self._sec:
                        times.append(when)
                    when += length
        else:
            times = grid[bisect.bisect_left(grid, self._sec):
                         bisect.bisect_right(grid, self._sec + self._lead)]
        return [self.height() * (1 - (when - self._sec) / self._lead)
                for when in sorted(times) if self._sec <= when <= self._sec + self._lead]

    def _nodes(self):
        geo = self.piano._geometry()
        if not self.show_notes or not geo or self._lead <= 0:
            return []
        whites, x0, _, kw, _ = geo
        loop = next(((start, end) for start, end in self._loops
                     if start <= self._sec < end), None)
        nodes = []
        for when, midi, color, duration in self._events:
            if not MIDI_LOW <= midi <= MIDI_HIGH:
                continue
            times = [when]
            if loop:
                start, end = loop
                if not start <= when < end:
                    continue
                duration = min(duration, end - when)
                length = end - start
                when += max(0, int((self._sec - when) // length)) * length
                times = []
                while when <= self._sec + self._lead:
                    if when + duration > self._sec:
                        times.append(when)
                    when += length
            white = midi if _is_white(midi) else midi - 1
            x = self.piano._wx(whites.index(white), whites, x0, kw)
            x += kw / 2 if _is_white(midi) else kw
            size = min(16.0, kw * (0.5 if _is_white(midi) else 0.35))
            for when in times:
                remaining = when - self._sec
                if when + duration > self._sec and remaining <= self._lead:
                    speed = self.height() / self._lead
                    length = duration * speed
                    bottom = self.height() - remaining * speed
                    nodes.append((x, bottom - length, size, length, color))
        return nodes

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(T.BG_INSET))
        p.setPen(QPen(QColor(T.BORDER_DEFAULT), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 8, 8)
        p.setClipRect(self.rect().adjusted(1, 1, -1, -1))
        geo = self.piano._geometry()
        if geo:
            whites, x0, _, kw, _ = geo
            p.setPen(QPen(QColor(T.BORDER_SUBTLE), .5))
            for i in range(len(whites)):
                x = self.piano._wx(i, whites, x0, kw) + kw / 2
                p.drawLine(int(x), 0, int(x), self.height())
        self._draw_chords(p)
        if self.show_notes:
            p.setPen(QPen(QColor(T.BORDER_SUBTLE), 1))
            for y in self._beat_lines():
                p.drawLine(0, int(y), self.width(), int(y))
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, width, length, color in self._nodes():
            gradient = QLinearGradient(0, y, 0, y + length)
            gradient.setColorAt(0, QColor(color).darker(145))
            gradient.setColorAt(1, QColor(color))
            p.setBrush(gradient)
            p.drawRoundedRect(QRectF(x - width / 2, y, width, max(3, length)), 3, 3)
            p.setBrush(QColor(color).lighter(140))
            p.drawRoundedRect(QRectF(x - width / 2, y + length - 2, width, 2), 1, 1)
        p.setPen(QPen(QColor(T.BORDER_ACTIVE), 2))
        p.drawLine(0, self.height() - 2, self.width(), self.height() - 2)
