"""재생 엔진 — 오디오 + 재생위치/seek (정의서 §9).

QtMultimedia.QMediaPlayer로 원본 오디오를 재생하고 position/seek을 제공한다.
스크럽 = position 점프(seek)이며, ML/재분석은 일절 재실행하지 않는다(§4).

위치는 항상 단조 시계(QElapsedTimer)로 이어 계산한다. QMediaPlayer.position()은 디코드 덩어리
단위(약 0.1초) 계단으로만 바뀌어 그대로 쓰면 화면이 끊기므로, 음원 보고는 시계 오차 보정에만 쓴다.
오디오가 없는 더미 타임라인·예비박(음수 시각)은 같은 시계를 보정 없이 쓴다.
"""
from __future__ import annotations

import os

from PyQt6.QtCore import QObject, Qt, QTimer, QElapsedTimer, pyqtSignal, QUrl

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    _HAS_MULTIMEDIA = True
except Exception:  # QtMultimedia 미설치 환경 폴백
    _HAS_MULTIMEDIA = False


TICK_MS = 16  # 위치 갱신 = 화면 프레임 주기(~60fps). 기본 Coarse 타이머는 Windows에서 ~31ms로 뭉개져 Precise로
# ponytail: 모니터 vsync와 맞물리진 않음(가끔 한 프레임 겹침/건너뜀) — 필요하면 QOpenGLWidget frameSwapped로 구동
SNAP_SEC = 0.3   # 음원 보고와 이만큼 어긋날 때만 바로 맞춤(버퍼링 사고) — 보고는 ~0.1초 계단이라 그 안은 무시
SNAP_REPORTS = 3 # 그 어긋남이 보고 이만큼 이어질 때만(시킹 직후 한 번 오는 옛 위치 보고는 무시)
WARM_MS = 400    # 로딩 직후 무음으로 미리 재생해 오디오 장치를 여는 시간(첫 재생 지연을 진입 때 치름)


class Playhead(QObject):
    """타임라인 재생 헤드. 위치는 항상 원본 음원의 초(float) 단위.

    positionChanged(sec): 매 틱 발생
    stateChanged(playing: bool)
    """
    positionChanged = pyqtSignal(float)
    stateChanged = pyqtSignal(bool)
    errorOccurred = pyqtSignal(str)

    def __init__(self, total_sec: float, audio_ref: str = "", parent=None):
        super().__init__(parent)
        self._total = max(0.0, total_sec)
        self._audio_ref = audio_ref or ""
        self._playing = False
        self._media_error = ""
        self._media_ready = True
        self._pending_seek = None

        self._use_audio = bool(self._audio_ref)
        self._player = None
        self._audio_out = None

        # 시계 상태(음원·예비박·더미 공통): 위치 = 기준점 + 기준점 이후 경과
        self._virt_base = 0.0          # 마지막 재생·시킹·보정 시점의 위치
        self._elapsed = QElapsedTimer()
        self._preroll = False         # 음수 시각은 가상 클럭, 원본 오디오는 0초부터
        self._warming = False         # 무음 예열 재생 중
        self._off = 0                 # 음원 보고가 SNAP_SEC 넘게 어긋난 연속 횟수

        if self._use_audio and _HAS_MULTIMEDIA:
            self._player = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self._audio_out.setVolume(1.0)
            self._player.setAudioOutput(self._audio_out)
            self._player.durationChanged.connect(self._on_duration)
            self._player.mediaStatusChanged.connect(self._on_media_status)
            self._player.errorOccurred.connect(self._on_media_error)
            self._player.positionChanged.connect(self._on_audio_position)
            if os.path.isfile(self._audio_ref):
                self._media_ready = False
                self._pending_seek = 0.0
                self._player.setSource(QUrl.fromLocalFile(self._audio_ref))
            else:
                self._media_error = f"음원 파일을 찾을 수 없어요: {self._audio_ref}"
        elif self._use_audio:
            self._media_error = "오디오 재생 모듈을 사용할 수 없어요."

        self._tick = QTimer(self)
        self._tick.setTimerType(Qt.TimerType.PreciseTimer)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)

    # ── 속성 ─────────────────────────────────────────────────────
    def total_sec(self) -> float:
        return self._total

    def is_playing(self) -> bool:
        return self._playing

    def position_sec(self) -> float:
        if self._ticking():
            return self._virt_base + self._elapsed.nsecsElapsed() / 1e9
        return self._virt_base

    def _ticking(self) -> bool:
        """시계가 흐르는 중 — 실제 음원 구간은 로딩·장치 예열이 끝나 재생을 건 뒤부터(그 전엔 멈춘 채 = 로딩)."""
        return self._playing and (self._preroll or not self._use_audio or self._media_ready and not self._warming)

    # ── 제어 ─────────────────────────────────────────────────────
    def set_volume(self, volume: float):
        if self._audio_out is not None:
            self._audio_out.setVolume(max(0.0, min(1.0, float(volume))))

    def play(self):
        if self._playing:
            return
        if self._media_error:
            self.errorOccurred.emit(self._media_error)
            return
        self._playing = True
        self._elapsed.restart()
        if self._use_audio and not self._preroll and self._media_ready and not self._warming:
            self._player.play()                       # 예열 중이면 예열이 끝날 때 출발(_end_warm)
        self._tick.start()
        self.stateChanged.emit(True)

    def pause(self):
        if not self._playing:
            return
        self._virt_base = self.position_sec()
        self._playing = False
        if self._use_audio and not self._preroll and not self._warming:
            self._player.pause()
        self._tick.stop()
        self.stateChanged.emit(False)
        self.positionChanged.emit(self.position_sec())

    def toggle(self):
        self.pause() if self._playing else self.play()

    def seek(self, sec: float):
        """스크럽 = 위치 점프. 재생 중/정지 모두 가능."""
        sec = min(sec, self._total if self._total > 0 else sec)
        self._preroll = sec < 0
        self._virt_base = sec
        self._elapsed.restart()        # setPosition이 바로 내는 음원 보고보다 먼저 기준점을 옮긴다
        if self._warming:
            pass                       # 예열이 끝날 때 이 위치로 맞춘다
        elif self._use_audio and not self._preroll:
            if not self._media_ready or self._pending_seek is not None:
                self._pending_seek = sec
            elif self._player is not None:
                self._player.setPosition(round(sec * 1000))
            if self._playing and self._media_ready and self._player is not None:
                self._player.play()
        else:
            if self._use_audio and self._player is not None:
                self._player.pause()
                self._player.setPosition(0)
                if not self._media_ready:
                    self._pending_seek = 0.0
        self.positionChanged.emit(self.position_sec())

    def stop(self):
        self.pause()
        self.seek(0.0)

    # ── 내부 ─────────────────────────────────────────────────────
    def _on_tick(self):
        pos = self.position_sec()
        if self._preroll and pos >= 0:
            self.seek(pos)
        if self._total > 0 and pos >= self._total:
            # 끝에서 정지 (구간반복은 비목표 §10)
            self.seek(self._total)
            self.pause()
            return
        self.positionChanged.emit(pos)

    def _on_duration(self, ms: int):
        if ms > 0 and self._total <= 0:
            self._total = ms / 1000.0

    def _on_media_status(self, status):
        if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                      QMediaPlayer.MediaStatus.BufferedMedia):
            if not self._media_ready and not self._preroll:
                self._elapsed.restart()   # 로딩 동안 멈춰 있던 시계는 지금부터 흐른다
            warm = not self._media_ready
            self._media_ready = True
            if self._pending_seek is not None:
                position = self._pending_seek
                self._pending_seek = None
                self._player.setPosition(round(position * 1000))
            if warm:
                self._warm_up()
            if (status == QMediaPlayer.MediaStatus.LoadedMedia and self._playing
                    and not self._preroll
                    and self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState):
                self._player.play()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.pause()

    def _warm_up(self):
        """오디오 장치를 무음 재생으로 미리 연다 — 첫 재생의 장치 오픈 지연(~0.4초)을 화면 진입(로딩) 때 치른다."""
        self._warming = True
        self._audio_out.setMuted(True)
        self._player.play()
        QTimer.singleShot(WARM_MS, self._end_warm)

    def _end_warm(self):
        """예열 끝 — 지금 위치로 맞추고, 그새 재생을 눌렀으면 이제 출발(시계와 음원이 같이)."""
        self._warming = False
        start = self._playing and not self._preroll
        if start:
            self._elapsed.restart()    # 지금부터 흐름(이동이 바로 내는 음원 보고보다 먼저)
        else:                          # 멈춤 → 일시정지 후 위치만(일시정지·이동·재생을 잇달아 하면 이동이 무시됨)
            self._player.pause()
        self._player.setPosition(round(max(0.0, self._virt_base) * 1000))   # 흐르는 채로 이동(장치는 열린 그대로)
        self._audio_out.setMuted(False)

    def _on_audio_position(self, ms: int):
        """화면 시계는 늘 1배속(보정으로 빨라지거나 느려지면 레일·노드 흐름이 출렁인다). 시작 지연은 장치 예열로
        없애고, 음원 보고와 SNAP_SEC 넘게 어긋날 때(버퍼링 사고)만 바로 맞춘다.
        ponytail: 남는 오차 = 예열된 장치의 시작 지연(실측 ~20~80ms)·시계 드리프트(수십 ppm) — 사용자 싱크 보정값으로.
        """
        if self._preroll or not self._ticking():
            return
        now = self.position_sec()
        err = ms / 1000.0 - now
        self._off = self._off + 1 if abs(err) > SNAP_SEC else 0
        if self._off >= SNAP_REPORTS:
            self._off = 0
            self._virt_base = now + err
            self._elapsed.restart()

    def _on_media_error(self, error, message=""):
        if error == QMediaPlayer.Error.NoError:
            return
        self._media_error = message or self._player.errorString() or "음원 재생에 실패했어요."
        self.pause()
        self.errorOccurred.emit(self._media_error)
