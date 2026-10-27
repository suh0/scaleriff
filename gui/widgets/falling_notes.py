"""낙하 노드 타이밍 모델 — 리프 음표의 레인 내 위치·길이(평면 좌표). 그리기는 Stage가 원근으로 한다."""
import bisect
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

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
        self._chord_grid = []
        self._loops = []
        self.show_notes = False            # 리프모드에서만 노드 낙하
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()                        # 화면엔 Stage가 그림

    def set_events(self, events, beat_sec, beat_grid=(), chord_grid=()):
        self._events = events
        self._lead = 4 * beat_sec
        self._beat = beat_sec
        self._beat_grid = list(beat_grid)
        self._chord_grid = list(chord_grid)
        self.update()

    def set_position(self, sec, loops=()):
        self._sec = sec
        self._loops = loops
        self.update()

    def _chord_lines(self):
        return self._beat_lines(self._chord_grid) if self._chord_grid else []

    def _beat_lines(self, grid=None):
        if self._lead <= 0 or self._beat <= 0:
            return []
        loop = next(((start, end) for start, end in self._loops
                     if start <= self._sec < end), None)
        grid = self._beat_grid if grid is None else grid
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
            size = kw * (0.8 if _is_white(midi) else 0.5)
            for when in times:
                remaining = when - self._sec
                if when + duration > self._sec and remaining <= self._lead:
                    speed = self.height() / self._lead
                    length = duration * speed
                    bottom = self.height() - remaining * speed
                    nodes.append((x, bottom - length, size, length, color))
        return nodes
