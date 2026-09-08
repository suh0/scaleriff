"""재생 엔진 — 오디오 + 재생위치/seek (정의서 §9).

QtMultimedia.QMediaPlayer로 원본 오디오를 재생하고 position/seek을 제공한다.
스크럽 = position 점프(seek)이며, ML/재분석은 일절 재실행하지 않는다(§4).

오디오가 없는 더미 타임라인을 위해 가상 클럭 모드를 함께 지원한다.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, QTimer, QElapsedTimer, pyqtSignal, QUrl

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    _HAS_MULTIMEDIA = True
except Exception:  # QtMultimedia 미설치 환경 폴백
    _HAS_MULTIMEDIA = False


TICK_MS = 25  # 위치 갱신 주기 (~40fps)


class Playhead(QObject):
    """타임라인 재생 헤드. 위치는 초(float) 단위.

    positionChanged(sec): 매 틱 발생
    stateChanged(playing: bool)
    """
    positionChanged = pyqtSignal(float)
    stateChanged = pyqtSignal(bool)

    def __init__(self, total_sec: float, audio_ref: str = "", parent=None):
        super().__init__(parent)
        self._total = max(0.0, total_sec)
        self._audio_ref = audio_ref or ""
        self._playing = False

        self._use_audio = bool(self._audio_ref) and _HAS_MULTIMEDIA
        self._player = None
        self._audio_out = None

        # 가상 클럭 상태
        self._virt_base = 0.0          # 마지막 재생 시작 시점의 누적 위치
        self._elapsed = QElapsedTimer()

        if self._use_audio:
            self._player = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_out)
            self._player.setSource(QUrl.fromLocalFile(self._audio_ref))
            if self._total <= 0:
                self._player.durationChanged.connect(self._on_duration)

        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)

    # ── 속성 ─────────────────────────────────────────────────────
    def total_sec(self) -> float:
        return self._total

    def is_playing(self) -> bool:
        return self._playing

    def position_sec(self) -> float:
        if self._use_audio and self._player is not None:
            return self._player.position() / 1000.0
        if self._playing:
            return self._virt_base + self._elapsed.elapsed() / 1000.0
        return self._virt_base

    # ── 제어 ─────────────────────────────────────────────────────
    def play(self):
        if self._playing:
            return
        self._playing = True
        if self._use_audio:
            self._player.play()
        else:
            self._elapsed.restart()
        self._tick.start()
        self.stateChanged.emit(True)

    def pause(self):
        if not self._playing:
            return
        if self._use_audio:
            self._player.pause()
        else:
            self._virt_base = self.position_sec()
        self._playing = False
        self._tick.stop()
        self.stateChanged.emit(False)
        self.positionChanged.emit(self.position_sec())

    def toggle(self):
        self.pause() if self._playing else self.play()

    def seek(self, sec: float):
        """스크럽 = 위치 점프. 재생 중/정지 모두 가능."""
        sec = max(0.0, min(sec, self._total if self._total > 0 else sec))
        if self._use_audio:
            self._player.setPosition(int(sec * 1000))
        else:
            self._virt_base = sec
            if self._playing:
                self._elapsed.restart()
        self.positionChanged.emit(self.position_sec())

    def stop(self):
        self.pause()
        self.seek(0.0)

    # ── 내부 ─────────────────────────────────────────────────────
    def _on_tick(self):
        pos = self.position_sec()
        if self._total > 0 and pos >= self._total:
            # 끝에서 정지 (구간반복은 비목표 §10)
            self.seek(self._total)
            self.pause()
            return
        self.positionChanged.emit(pos)

    def _on_duration(self, ms: int):
        if ms > 0 and self._total <= 0:
            self._total = ms / 1000.0
