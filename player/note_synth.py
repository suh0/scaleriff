"""사용자 연주음 신디 — 친 음(MIDI/마우스)을 피아노 음색으로 즉시 소리낸다.

저지연 재생을 위해 음마다 16-bit PCM WAV을 미리/지연 렌더링해 캐시하고,
음별 QSoundEffect로 재생한다(자연스러운 폴리포니, 키 떼면 자연 감쇠).
"""
from __future__ import annotations

import os
import numpy as np

from PyQt6.QtCore import QObject, QUrl

SR = 44100   # 샘플레이트


def _midi_to_freq(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _note_wave(freq: float, dur: float, timbre: str = "piano") -> np.ndarray:
    """간단한 가산합성 피아노 톤 — 기음+배음 + 지수 감쇠."""
    n = int(SR * dur)
    t = np.linspace(0.0, dur, n, endpoint=False)
    harmonics = [(1, 1.0), (2, 0.5), (3, 0.25), (4, 0.12), (5, 0.06)]
    y = np.zeros(n, dtype=np.float64)
    for h, amp in harmonics:
        y += amp * np.sin(2.0 * np.pi * freq * h * t)
    env = np.exp(-3.0 * t)                  # 피아노식 감쇠
    atk = min(n, int(0.005 * SR))           # 짧은 어택(클릭 방지)
    if atk > 0:
        env[:atk] *= np.linspace(0.0, 1.0, atk)
    return y * env

try:
    from PyQt6.QtMultimedia import QSoundEffect
    _HAS_SE = True
except Exception:
    _HAS_SE = False

_CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "cache", "notes")
os.makedirs(_CACHE, exist_ok=True)

NOTE_DUR = 1.1   # 한 음 길이(초) — 피아노 감쇠


def _render_note_wav(midi: int) -> str:
    path = os.path.join(_CACHE, f"piano_{midi}.wav")
    if os.path.exists(path):
        return path
    import soundfile as sf
    y = _note_wave(_midi_to_freq(midi), NOTE_DUR, "piano")
    mx = float(np.max(np.abs(y))) or 1.0
    pcm = (y / mx * 0.75 * 32767).astype(np.int16)   # QSoundEffect는 PCM 선호
    sf.write(path, pcm, SR, subtype="PCM_16")
    return path


class NotePlayer(QObject):
    def __init__(self, parent=None, prewarm=range(60, 72)):
        super().__init__(parent)
        self._fx: dict[int, object] = {}
        if _HAS_SE:
            for m in prewarm:     # 표시 범위(C4~B5) 미리 준비
                self._effect(m)

    def _effect(self, midi: int):
        if midi in self._fx:
            return self._fx[midi]
        if not _HAS_SE:
            return None
        eff = QSoundEffect(self)
        eff.setSource(QUrl.fromLocalFile(_render_note_wav(midi)))
        eff.setVolume(0.7)
        self._fx[midi] = eff
        return eff

    def play_note(self, midi: int):
        eff = self._effect(midi)
        if eff is not None:
            eff.play()
