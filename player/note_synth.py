"""사용자 연주음 신디 — 친 음(MIDI/마우스)을 피아노 음색으로 즉시 소리낸다.

저지연 재생을 위해 음마다 16-bit PCM WAV을 미리/지연 렌더링해 캐시하고,
음/채널별 QSoundEffect로 재생하며 note-off와 페달로 음길이를 제어한다.
"""
from __future__ import annotations

import os
import numpy as np

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl

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

NOTE_DUR = 6.0   # 누른 동안 재생할 피아노의 자연 감쇠
DEFAULT_NOTE_DUR = 1.1
RELEASE_SEC = 0.08   # note-off 페이드 — 즉시 stop()은 파형을 잘라 '딱' 팝이 난다
_FADE_STEPS = 8


def _render_silence_wav() -> str:
    """예열용 진짜 무음 WAV — 볼륨 트릭 없이 장치만 연다."""
    path = os.path.join(_CACHE, "silence.wav")
    if not os.path.exists(path):
        import soundfile as sf
        sf.write(path, np.zeros(int(SR * 0.12), dtype=np.int16), SR,
                 subtype="PCM_16")
    return path


def render_click_wav(freq: float) -> str:
    """메트로놈 클릭 — 150ms 사인이 스스로 0까지 감쇠(stop() 없이 재생 → 끊김 팝 없음).

    30ms처럼 너무 짧으면 Windows QSoundEffect가 출력 장치를 여는 동안 통째로 묻힌다.
    """
    path = os.path.join(_CACHE, f"click_v2_{int(freq)}.wav")
    if not os.path.exists(path):
        import soundfile as sf
        t = np.arange(int(SR * 0.15)) / SR
        y = np.sin(2.0 * np.pi * freq * t) * np.exp(-t / 0.025)
        y[-int(0.01 * SR):] *= np.linspace(1.0, 0.0, int(0.01 * SR))   # 끝 10ms 페이드
        y[:int(0.001 * SR)] *= np.linspace(0.0, 1.0, int(0.001 * SR))   # 1ms 어택
        sf.write(path, (y * 0.8 * 32767).astype(np.int16), SR, subtype="PCM_16")
    return path


def _render_note_wav(midi: int) -> str:
    path = os.path.join(_CACHE, f"piano_v2_{midi}.wav")
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
    # MIDI는 0~15 채널, 리프/재청취는 16/17의 독립 보이스를 사용한다.
    # 입력 건반은 미리 로드하고 예정 리프는 preload()로 대비한다.
    def __init__(self, parent=None, prewarm=range(48, 84)):
        super().__init__(parent)
        self._fx: dict[object, object] = {}
        self._volume = 0.7
        self._held: set[tuple[int, int]] = set()
        self._sustained: set[tuple[int, int]] = set()
        self._pedal: set[int] = set()
        self._velocity: dict[tuple[int, int], int] = {}
        self._generation: dict[tuple[int, int], int] = {}
        if _HAS_SE:
            for m in prewarm:
                self._effect(m)

    def preload(self, midis, channel: int = 16):
        """재생 예정 음들의 이펙트를 미리 생성(비동기 로드 시작)만 해 둔다."""
        for m in midis:
            self._effect(m, channel)

    def _effect(self, midi: int, channel: int = 0):
        key = (channel, midi)
        if key in self._fx:
            return self._fx[key]
        if not _HAS_SE:
            return None
        eff = QSoundEffect(self)
        eff.setSource(QUrl.fromLocalFile(_render_note_wav(midi)))
        eff.setVolume(self._volume)
        eff.statusChanged.connect(
            lambda e=eff, m=midi: e.status() == QSoundEffect.Status.Error
            and print(f"[note_synth] 로드 실패 midi={m}: {e.source().toString()}"))
        self._fx[key] = eff
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

    def note_on(self, midi: int, velocity: int = 100, channel: int = 0):
        midi, channel = int(midi), int(channel)
        velocity = max(0, min(127, int(velocity)))
        if velocity == 0:
            self.note_off(midi, channel)
            return
        if not 0 <= midi <= 127 or not 0 <= channel <= 17:
            return
        key = (channel, midi)
        self._generation[key] = self._generation.get(key, 0) + 1
        self._held.add(key)
        self._sustained.discard(key)
        self._velocity[key] = velocity
        eff = self._effect(midi, channel)
        if eff is None:
            return
        if eff.status() == QSoundEffect.Status.Error:   # 로드 실패 → 1회 재시도
            self._fx.pop(key, None)
            eff = self._effect(midi, channel)
            if eff is None:
                return
        eff.stop()
        eff.setVolume(self._volume * velocity / 127.0)
        eff.play()

    def note_off(self, midi: int, channel: int = 0):
        key = (int(channel), int(midi))
        self._held.discard(key)
        if key not in self._velocity:
            return
        if channel in self._pedal:
            self._sustained.add(key)
        else:
            self._release(key)

    def _release(self, key):
        self._sustained.discard(key)
        velocity = self._velocity.pop(key, None)
        if self._fx.get(key) is None or velocity is None:
            return
        # ponytail: 같은 음을 페이드 중(80ms 안)에 재타건하면 stop()+play() 팝은 남는다 — 키당 보이스 2개로 교대하면 해결
        self._generation[key] = generation = self._generation.get(key, 0) + 1
        self._fade(key, generation, self._volume * velocity / 127.0, _FADE_STEPS)

    def _fade(self, key, generation, start, left):
        """볼륨을 계단식으로 내린 뒤 stop() — 새 note_on(세대 변경)이 오면 중단."""
        eff = self._fx.get(key)
        if eff is None or self._generation.get(key) != generation:
            return
        if left <= 0:
            eff.stop()
            return
        eff.setVolume(start * (left - 1) / _FADE_STEPS)
        QTimer.singleShot(round(RELEASE_SEC * 1000 / _FADE_STEPS), Qt.TimerType.PreciseTimer,
                          lambda: self._fade(key, generation, start, left - 1))

    def set_pedal(self, down: bool, channel: int = 0):
        channel = int(channel)
        if down:
            self._pedal.add(channel)
        else:
            self._pedal.discard(channel)
            for key in tuple(self._sustained):
                if key[0] == channel and key not in self._held:
                    self._release(key)

    def stop_all(self):
        for key in tuple(self._velocity):
            self._generation[key] = self._generation.get(key, 0) + 1
            self._release(key)
        self._held.clear()
        self._pedal.clear()

    def set_volume(self, volume: float):
        self._volume = max(0.0, min(1.0, float(volume)))
        for key, velocity in self._velocity.items():
            eff = self._fx.get(key)
            if eff is not None:
                eff.setVolume(self._volume * velocity / 127.0)

    def play_note(self, midi: int, duration: float | None = None,
                  velocity: int = 100, channel: int = 16):
        """리프용 한 음. 이전 타이머가 재타건한 새 음을 끄지 않게 한다."""
        self.note_on(midi, velocity, channel)
        key = (int(channel), int(midi))
        generation = self._generation.get(key)
        duration = DEFAULT_NOTE_DUR if duration is None else max(0.0, float(duration))
        QTimer.singleShot(round(duration * 1000),
                          lambda: self._finish_note(key, generation))

    def _finish_note(self, key, generation):
        if self._generation.get(key) == generation:
            self.note_off(key[1], key[0])


_shared: NotePlayer | None = None


def shared_player() -> NotePlayer:
    """앱 전역 공유 NotePlayer — 화면마다 만들면 이펙트가 배로 늘어난다."""
    global _shared
    if _shared is None:
        _shared = NotePlayer()
    return _shared
