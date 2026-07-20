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


def _render_silence_wav() -> str:
    """예열용 진짜 무음 WAV — 볼륨 트릭 없이 장치만 연다."""
    path = os.path.join(_CACHE, "silence.wav")
    if not os.path.exists(path):
        import soundfile as sf
        sf.write(path, np.zeros(int(SR * 0.12), dtype=np.int16), SR,
                 subtype="PCM_16")
    return path


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
    # 상시 보유 이펙트는 화면 건반 전 음역(C3~B5 = 48~83)만 미리 로드한다.
    # 건반 클릭·MIDI·리프 재생 모두 이 안 → lazy 생성(비동기 로드) 무음 방지.
    # 이 정도(36개)는 백엔드 보이스 한도 안. 범위 밖은 preload()로 대비.
    def __init__(self, parent=None, prewarm=range(48, 84)):
        super().__init__(parent)
        self._fx: dict[int, object] = {}
        if _HAS_SE:
            for m in prewarm:
                self._effect(m)

    def preload(self, midis):
        """재생 예정 음들의 이펙트를 미리 생성(비동기 로드 시작)만 해 둔다."""
        for m in midis:
            self._effect(m)

    def _effect(self, midi: int):
        if midi in self._fx:
            return self._fx[midi]
        if not _HAS_SE:
            return None
        eff = QSoundEffect(self)
        eff.setSource(QUrl.fromLocalFile(_render_note_wav(midi)))
        eff.setVolume(0.7)
        eff.statusChanged.connect(
            lambda e=eff, m=midi: e.status() == QSoundEffect.Status.Error
            and print(f"[note_synth] 로드 실패 midi={m}: {e.source().toString()}"))
        self._fx[midi] = eff
        return eff

    def warmup(self):
        """오디오 장치 무음 예열 — 첫 재생의 장치 오픈 지연으로
        초반 음들이 몰려(빨라져) 들리는 것을 방지.

        내용 자체가 무음인 WAV를 재생 — setVolume(0) 트릭은 백엔드에
        비동기 적용이라 첫 버퍼가 새어나와(어택 블립) 폐기했다.
        """
        if not _HAS_SE:
            return
        eff = self._fx.get(-1)
        if eff is None:
            eff = QSoundEffect(self)
            eff.setSource(QUrl.fromLocalFile(_render_silence_wav()))
            self._fx[-1] = eff
        eff.play()

    def play_note(self, midi: int):
        eff = self._effect(midi)
        if eff is None:
            return
        if eff.status() == QSoundEffect.Status.Error:   # 로드 실패 → 1회 재시도
            self._fx.pop(midi, None)
            eff = self._effect(midi)
            if eff is None:
                return
        eff.play()


_shared: NotePlayer | None = None


def shared_player() -> NotePlayer:
    """앱 전역 공유 NotePlayer — 화면마다 만들면 이펙트가 배로 늘어난다."""
    global _shared
    if _shared is None:
        _shared = NotePlayer()
    return _shared
