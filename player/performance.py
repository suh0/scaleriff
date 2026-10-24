"""원본 오디오 초 기준 MIDI 연주 기록. Qt/오디오 장치와 독립적이다."""
from copy import deepcopy


class PerformanceRecorder:
    def __init__(self):
        self.active = False
        self.notes = []
        self._held = {}
        self._pedal = {}
        self.start_sec = 0.0

    def begin(self, start_sec):
        self.cancel()
        self.start_sec = start_sec
        self.active = True

    def _close(self, key, sec):
        note = self._held.pop(key, None)
        if note is not None:
            note["duration_sec"] = max(0.0, sec - note["start_sec"])
            note.setdefault("key_duration_sec", note["duration_sec"])
            self.notes.append(note)

    def event(self, event, sec):
        if not self.active or sec < self.start_sec:
            return
        channel = event.get("channel", 0)
        if event.get("type") == "pedal":
            down = bool(event.get("down", event.get("pedal", False)))
            self._pedal[channel] = down
            if not down:
                for key, note in list(self._held.items()):
                    if key[0] == channel and "key_duration_sec" in note:
                        self._close(key, sec)
            return
        midi = event.get("pitch", event.get("midi"))
        if midi is None:
            return
        key = (channel, midi)
        if event.get("is_on", False):
            self._close(key, sec)
            self._held[key] = {"midi": midi, "start_sec": sec, "duration_sec": 0.0,
                               "velocity": event.get("velocity", 100), "channel": channel}
        elif key in self._held:
            self._held[key]["key_duration_sec"] = max(0.0, sec - self._held[key]["start_sec"])
            if not self._pedal.get(channel, False):
                self._close(key, sec)

    def finish(self, end_sec):
        if not self.active:
            return []
        for key in list(self._held):
            self._close(key, end_sec)
        self.active = False
        return deepcopy(sorted(self.notes, key=lambda n: n["start_sec"]))

    def cancel(self):
        self.active = False
        self.notes = []
        self._held = {}
        self._pedal = {}
