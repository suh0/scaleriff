"""리프 음표를 재생 위치에 맞춰 해당 건반으로 떨어뜨리는 예고."""
import bisect
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QLinearGradient
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
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

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
        if not geo or self._lead <= 0:
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
