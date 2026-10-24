"""MIDI 키보드 입력 (정의서 §9).

mido(+python-rtmidi 백엔드)로 실시간 노트 온/오프를 QThread에서 수신해
note_event(dict)에 강약·채널·수신 시각·페달을 보존한다.
note_received(midi, is_on)는 기존 건반 표시 호출자의 호환용이다.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QThread, pyqtSignal

try:
    import mido
    _HAS_MIDO = True
except Exception:
    _HAS_MIDO = False


class MidiInput(QThread):
    note_received = pyqtSignal(int, bool)   # (midi pitch, is_note_on)
    note_event = pyqtSignal(dict)
    errorOccurred = pyqtSignal(str)
    connectionChanged = pyqtSignal(str)
    _connection_update = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._port = None
        self._port_name = ""
        self._running = False
        self._connection_update.connect(self._emit_connection)

    @property
    def port_name(self) -> str:
        return self._port_name

    @staticmethod
    def list_ports() -> list[str]:
        if not _HAS_MIDO:
            return []
        try:
            return mido.get_input_names()
        except Exception:
            return []

    def open_port(self, name: str | None = None) -> bool:
        """기존 수신을 끝낸 뒤 선택 장치를 연다. 수신 시작은 start()가 맡는다."""
        self.stop()
        if self.isRunning():
            self.errorOccurred.emit("이전 MIDI 수신이 종료되지 않았어요.")
            return False
        if not _HAS_MIDO:
            return False
        names = self.list_ports()
        name = name if name is not None else (names[0] if names else "")
        if name not in names:
            return False
        try:
            self._port = mido.open_input(name)
            self._port_name = name
            self._running = True
            self._connection_update.emit()
            return True
        except Exception as exc:
            self._port = None
            self.errorOccurred.emit(f"MIDI 장치를 열지 못했어요: {exc}")
            return False

    def open_first_available(self) -> bool:
        return self.open_port()

    def run(self):
        port = self._port
        if port is None:
            return
        try:
            while self._running:
                for msg in port.iter_pending():
                    received = time.monotonic()
                    if msg.type in ("note_on", "note_off"):
                        is_on = msg.type == "note_on" and msg.velocity > 0
                        self.note_event.emit({
                            "type": "note", "pitch": int(msg.note), "is_on": is_on,
                            "velocity": int(msg.velocity), "channel": int(msg.channel),
                            "received_time": received,
                        })
                        self.note_received.emit(msg.note, is_on)
                    elif msg.type == "control_change" and msg.control == 64:
                        down = msg.value >= 64
                        self.note_event.emit({
                            "type": "pedal", "down": down, "pedal": down,
                            "value": int(msg.value), "channel": int(msg.channel),
                            "received_time": received,
                        })
                self.msleep(5)
        except Exception as exc:
            self.errorOccurred.emit(f"MIDI 연결이 끊겼어요: {exc}")
        finally:
            self._running = False
            self._close_port(port)

    def stop(self):
        self._running = False
        if QThread.currentThread() is not self:
            self.wait(500)
        if not self.isRunning() and self._port is not None:
            self._close_port(self._port)

    def _close_port(self, port):
        try:
            port.close()
        except Exception:
            pass
        if self._port is port:
            self._port = None
            self._port_name = ""
            self._connection_update.emit()

    def _emit_connection(self):
        # 이전 수신 스레드의 종료 알림이 새 연결 상태를 덮지 않게 현재 값을 읽는다.
        self.connectionChanged.emit(self._port_name)
