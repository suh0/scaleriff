"""낙하 노드 타이밍 모델 — 리프 음표의 레인 내 위치·길이(평면 좌표). 그리기는 Stage가 원근으로 한다."""
import bisect
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from gui.widgets.piano import MIDI_LOW, MIDI_HIGH, _is_white

PERFECT_SEC = 0.06   # 이 안이면 PERFECT
HIT_SEC = 0.18       # 이 안이면 EARLY/LATE, 밖이면 판정 안 함


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
        self._detour = []
        self._hit = set()                  # 맞힌 노드 회차 (시각, 음)
        self.show_notes = False            # 리프모드에서만 노드 낙하
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()                        # 화면엔 Stage가 그림

    def set_events(self, events, beat_sec, beat_grid=(), chord_grid=(), detour=()):
        self._events = events
        self._lead = 4 * beat_sec
        self._beat = beat_sec
        self._beat_grid = list(beat_grid)
        self._chord_grid = list(chord_grid)
        self._detour = list(detour)        # 키 밖 코드 구간 [(start, end)] — 박자선 주황
        self._hit = set()
        self.update()

    def set_position(self, sec):
        if sec < self._sec - 0.05:         # 되감기 시킹 → 다시 올 노드의 판정 기록 지움
            self._hit = {h for h in self._hit if h[0] < sec}
        self._sec = sec
        self.update()

    def _chord_lines(self):
        return self._beat_lines(self._chord_grid) if self._chord_grid else []

    def _beat_lines(self, grid=None):
        return [y for y, _ in self._lines(grid)]

    def in_detour(self, when):
        # 매 프레임 그리기 중 호출 — any(제너레이터)는 조기 종료 때 GeneratorExit를 내고,
        # VS Code 디버거(Py3.12)가 거기서 그리기 도중 멈춘 뒤 재개하면 Qt가 충돌한다.
        for a, b in self._detour:
            if a <= when < b:
                return True
        return False

    def _lines(self, grid=None):
        """(레인 y, 원본 시각) — 시각은 키 밖 코드 구간 색 판정용."""
        if self._lead <= 0 or self._beat <= 0:
            return []
        grid = self._beat_grid if grid is None else grid
        if not grid:
            first = int(self._sec // self._beat)
            times = [(first + i) * self._beat for i in range(6)]
        else:
            times = grid[bisect.bisect_left(grid, self._sec):bisect.bisect_right(grid, self._sec + self._lead)]
        return [(self.height() * (1 - (when - self._sec) / self._lead), when)
                for when in times if self._sec <= when <= self._sec + self._lead]

    def _x(self, midi):
        whites, x0, _, kw, _ = self.piano._geometry()
        white = midi if _is_white(midi) else midi - 1
        x = self.piano._wx(whites.index(white), whites, x0, kw)
        return x + (kw / 2 if _is_white(midi) else kw)

    def judge(self, midi, sec):
        """누른 음을 가장 가까운 같은 음 노드와 맞춰 판정 → (문구, 평면 x) 또는 None. 맞힌 노드는 사라진다."""
        if not self.show_notes or not MIDI_LOW <= midi <= MIDI_HIGH:
            return None
        best = None
        for when, m, _, _ in self._events:
            if m != midi:
                continue
            key = (round(when, 3), midi)
            if abs(when - sec) <= HIT_SEC and key not in self._hit and (
                    best is None or abs(when - sec) < abs(best[0] - sec)):
                best = (when, key)
        if best is None:
            return None
        self._hit.add(best[1])
        dt = sec - best[0]
        label = "PERFECT" if abs(dt) <= PERFECT_SEC else ("EARLY" if dt < 0 else "LATE")
        return label, self._x(midi)

    def _nodes(self):
        geo = self.piano._geometry()
        if not self.show_notes or not geo or self._lead <= 0:
            return []
        kw = geo[3]
        nodes = []
        for when, midi, color, duration in self._events:
            remaining = when - self._sec
            if not MIDI_LOW <= midi <= MIDI_HIGH or when + duration <= self._sec or remaining > self._lead \
                    or (round(when, 3), midi) in self._hit:
                continue
            speed = self.height() / self._lead
            length = duration * speed
            bottom = self.height() - remaining * speed
            nodes.append((self._x(midi), bottom - length, kw * (0.8 if _is_white(midi) else 0.5), length, color))
        return nodes
