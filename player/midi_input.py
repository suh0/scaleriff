"""MIDI 키보드 입력 (정의서 §9).

mido(+python-rtmidi 백엔드)로 실시간 노트 온/오프를 QThread에서 수신해
note_received(midi, is_on) 시그널로 넘긴다. 연주음(§9)과 건반 표시의 입력원.
"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

try:
    import mido
    _HAS_MIDO = True
except Exception:
    _HAS_MIDO = False


class MidiInput(QThread):
    note_received = pyqtSignal(int, bool)   # (midi pitch, is_note_on)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._port = None
        self._running = False

    @staticmethod
    def list_ports() -> list[str]:
        if not _HAS_MIDO:
            return []
        try:
            return mido.get_input_names()
        except Exception:
            return []

    def open_first_available(self) -> bool:
        if not _HAS_MIDO:
            return False
        names = self.list_ports()
        if not names:
            return False
        try:
            self._port = mido.open_input(names[0])
            return True
        except Exception:
            self._port = None
            return False

    def run(self):
        if self._port is None:
            return
        self._running = True
        while self._running:
            for msg in self._port.iter_pending():
                if msg.type == "note_on" and msg.velocity > 0:
                    self.note_received.emit(msg.note, True)
                elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                    self.note_received.emit(msg.note, False)
            self.msleep(5)

    def stop(self):
        self._running = False
        self.wait(200)
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None
