"""리프 음표를 재생 위치에 맞춰 해당 건반으로 떨어뜨리는 예고."""
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen
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
        self._loops = []
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def set_events(self, events, beat_sec):
        self._events = events
        self._lead = 4 * beat_sec
        self.update()

    def set_position(self, sec, loops=()):
        self._sec = sec
        self._loops = loops
        self.update()

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
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, width, length, color in self._nodes():
            p.setBrush(QColor(color))
            p.drawRoundedRect(QRectF(x - width / 2, y, width, length), 3, 3)
