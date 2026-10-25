"""[2a] 박자 조정 화면 (§3.5 2차) — 분석 직후 마디선/BPM 확정.

화면 순서: 박자 3단계(시작점 → 끝부분 박자 → 예비박) → 코드 편집(세로 스크롤).
- 초기 격자 = 자동 인식값, 인식된 비트는 확대바에 흐리게 남긴다.
- 1단계: 클릭한 곳이 1마디(격자 평행이동), 마디선 드래그도 평행이동.
- 2단계: 끝부분 마디선 드래그 = 시작점 고정·BPM 조정(직접 입력도 가능).
- 3단계: 예비박 마디 수(코드표 제외, 연습 화면 재생 시작점). 확정 시에만 재격자화.
- 클릭·드래그한 마디선은 검출 비트 근처(SNAP_PX)에서 그 비트로 붙는다.
- 재생은 스페이스바만: 1마디부터 재생/정지(마우스로는 재생 안 함), 재생 중 메트로놈.
- 코드표 직접 조작: 칸 클릭 = 코드 수정, 칸 드래그 = 루프 지정(놓으면 이름 입력).
"""
from __future__ import annotations

import wave
import math
import bisect

import numpy as np

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QScrollArea, QInputDialog, QFrame,
    QGraphicsOpacityEffect, QLayout, QMenu, QStackedWidget
)
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QCursor, QShortcut, QKeySequence
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QTimer, QElapsedTimer, QUrl, QEvent
from PyQt6.QtMultimedia import QSoundEffect

from gui import theme as T
from gui.anim import stagger
from gui.widgets.flow_header import FlowHeader
from analyze.theory import (
    parse_chord, scale_pcs, degree_for, diatonic_option, pc_name,
)
from player.timeline import ScaleOption
from player.playhead import Playhead
from player.note_synth import render_click_wav
from build.real_builder import regrid_timeline
from ml.generate import bake_segment, bake_examples
from gui.widgets.busy_overlay import run_busy

ZOOM_SEC = 10.0      # 확대 창 길이
EDGE_SEC = 5.0       # 격자는 음원 앞뒤로 이만큼까지만(예비박 시작·코드 인식 끝)
END_GRAB_PX = 10     # 코드 인식 끝 핸들을 잡는 거리
WAVE_BUCKETS = 300   # 확대 창 파형 해상도(컬럼 수)
BARS_PER_ROW = 8
CELL_W = 86          # 마디 칸 폭
CLICK_PX = 3         # 이 이하로 움직이고 놓으면 드래그가 아니라 클릭
SNAP_PX = 8          # 검출 비트에 이만큼 가까워지면 자석처럼 붙음
METRO_HI_HZ, METRO_LO_HZ = 1760.0, 1320.0   # 강박/약박 클릭 높이
METRO_AHEAD = 0.05   # 클릭 예약 선행 시간(초) — 틱 간격(25ms)보다 길게
# 수동 코드 수정 선택지(접미사). parse_chord가 인식하는 표기.
_EDIT_SUFFIXES = ["", "m", "7", "maj7", "m7", "m7b5", "dim", "6", "m6", "sus4"]


def _wave_level(path: str) -> float:
    """곡 전체의 큰 소리 크기(|진폭| 상위 0.5%, 1.0 = 최대) — 곡마다 파형 높이를 맞추는 기준.

    최댓값 대신 분위수: 순간 튀는 소리 하나로 곡 전체가 작아 보이지 않게.
    무음·읽기 실패는 1.0(절대 크기 그대로).
    """
    try:
        with wave.open(path, "rb") as f:
            if f.getsampwidth() != 2:
                return 1.0
            a = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
    except (OSError, wave.Error, EOFError):
        return 1.0
    if not a.size:
        return 1.0
    level = float(np.percentile(np.abs(a[::10].astype(np.int32)), 99.5)) / 32768.0
    return level if level >= 0.05 else 1.0


def _wave_peaks(path: str, t0: float, t1: float,
                buckets: int = WAVE_BUCKETS, level: float = 1.0) -> list[tuple[float, float]]:
    """분석 WAV(PCM16 모노)의 [t0,t1) 구간 min/max 피크(level 기준 ±1로 자름). 실패 시 []."""
    try:
        with wave.open(path, "rb") as f:
            if f.getsampwidth() != 2:
                return []
            sr, ch = f.getframerate(), f.getnchannels()
            a = max(0, int(t0 * sr))
            b = min(f.getnframes(), int(t1 * sr))
            if b <= a:
                return []
            f.setpos(a)
            samples = np.frombuffer(f.readframes(b - a), dtype=np.int16)[::ch]
        step = max(1, len(samples) // buckets)
        n = min(buckets, len(samples) // step)
        c = samples[:n * step].reshape(n, step) / (32768.0 * level)
        return list(zip(np.maximum(c.min(1), -1.0).tolist(), np.minimum(c.max(1), 1.0).tolist()))
    except (OSError, wave.Error, EOFError):
        return []


class ZoomBar(QWidget):
    """확대 재생바 — 구간의 마디/박/분할 격자 + 재생 헤드. 마디선 드래그 가능."""
    barDragged = pyqtSignal(int, float)   # (전역 마디 인덱스 k, 드래그 위치 초)
    clicked = pyqtSignal(float)           # 제자리 클릭(위치 초)
    endDragged = pyqtSignal(float)        # 코드 인식 끝 핸들 드래그(위치 초)
    endReleased = pyqtSignal()            # 끝 핸들 놓음
    dragStarted = pyqtSignal()            # 드래그(마디선·끝 핸들) 시작
    dragFinished = pyqtSignal()           # 드래그 후 놓음

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(96)
        self.setCursor(Qt.CursorShape.SizeHorCursor)
        self._t0, self._t1 = 0.0, ZOOM_SEC
        self._beat_at = None              # 박 번호 → 시각(0 = 1마디 첫 박)
        self._index_at = None             # 시각 → (분수) 박 번호
        self._beats = 4
        self._lead = 1                    # 첫 마디 앞 예비박 마디 수(음영)
        self._ghost: list[float] = []     # 자동 인식 비트(흐린 선)
        self._pos = None
        self._drag_k: int | None = None
        self._drag_x = 0.0
        self._drag_sec = 0.0
        self._drag_sec_per_px = 0.0
        self._moved = False
        self._drag_win = (0.0, ZOOM_SEC)  # 드래그 허용 범위(누를 때의 창)
        self.draggable = True             # False면 클릭(재생)만
        self._end: float | None = None    # 코드 인식 끝(굵은 선) — 이후는 음영
        self.end_draggable = False
        self.pan_bars = True              # 마디선 드래그 = 음원 끌기(False면 선이 마우스를 따라감)
        self._end_drag = False
        self._peaks: list[tuple[float, float]] = []
        self._wave_t0, self._wave_t1 = 0.0, ZOOM_SEC

    def set_window(self, t0: float, t1: float):
        self._t0, self._t1 = t0, max(t1, t0 + 0.1)
        self.update()

    def set_grid(self, beat_at, index_at, beats: int, lead: int = 1):
        self._beat_at, self._index_at, self._beats = beat_at, index_at, beats
        self._lead = lead
        self.update()

    def set_end(self, t: float | None):
        self._end = t
        self.update()

    @property
    def dragging(self) -> bool:
        return self._end_drag or (self._drag_k is not None and self._moved)

    def set_ghost(self, times: list[float]):
        self._ghost = list(times)
        self.update()

    def set_position(self, sec: float):
        self._pos = sec
        self.update()

    def set_wave(self, peaks: list[tuple[float, float]], t0=0.0, t1=ZOOM_SEC):
        self._peaks = peaks
        self._wave_t0, self._wave_t1 = t0, t1
        self.update()

    # ── 좌표 변환 ────────────────────────────────────────────────
    def _sec_to_x(self, sec: float) -> float:
        return (sec - self._t0) / (self._t1 - self._t0) * self.width()

    def _x_to_sec(self, x: float) -> float:
        return self._t0 + x / max(1, self.width()) * (self._t1 - self._t0)

    # ── 마디선 드래그: 누른 곳에서 가장 가까운 마디선을 잡아 이동 ──
    def mousePressEvent(self, e):
        if self._beat_at is None:
            return
        x = e.position().x()
        self._drag_win = (self._t0, self._t1)
        self._drag_t0 = self._t0
        self._drag_x = x
        self._drag_sec_per_px = (self._t1 - self._t0) / max(1, self.width())
        self._moved = False
        if (self.end_draggable and self._end is not None
                and abs(x - self._sec_to_x(self._end)) <= END_GRAB_PX):
            self._end_drag = True               # 끝 핸들 잡기(마디선 드래그보다 우선)
            return
        sec = self._x_to_sec(x)
        self._drag_k = max(-self._lead, round(self._index_at(sec) / self._beats))
        self._drag_sec = self._beat_at(self._drag_k * self._beats)

    def mouseMoveEvent(self, e):
        dx = e.position().x() - self._drag_x
        if self._end_drag:                      # 끝 핸들: 선을 끌고, 놓으면 창이 끝선 기준으로 이동
            if not self._moved:
                self._moved = True
                self.dragStarted.emit()
            self.endDragged.emit(self._clamp(self._x_to_sec(e.position().x())))
        elif self._drag_k is not None:
            started = not self._moved
            self._moved = self.draggable and (self._moved or abs(dx) > CLICK_PX)
            if started and self._moved:
                self.dragStarted.emit()
            if self._moved and not self.pan_bars:
                self.barDragged.emit(self._drag_k,
                                     self._clamp(self._drag_sec + dx * self._drag_sec_per_px))
            elif self._moved:
                # 음원을 끈다: 잡은 마디선은 화면 제자리, 창(파형·점선)이 손을 따라 움직인다
                # — 보이는 창 밖으로도 계속 옮길 수 있다.
                self.barDragged.emit(self._drag_k, self._drag_sec - dx * self._drag_sec_per_px)
                t0 = self._drag_t0 + self._beat_at(self._drag_k * self._beats) - self._drag_sec
                self.set_window(t0, t0 + (self._t1 - self._t0))

    def _clamp(self, sec: float) -> float:
        """끝 핸들·2단계 마디선 위치는 누를 때의 창 안으로만 — 격자가 끝없이 밀리지 않게."""
        return min(max(sec, self._drag_win[0]), self._drag_win[1])

    def mouseReleaseEvent(self, e):
        if self._end_drag:
            self._end_drag = False
            self.endReleased.emit()
            if self._moved:
                self.dragFinished.emit()
            return
        if self._drag_k is not None:
            if self._moved:
                self.dragFinished.emit()
            else:
                self.clicked.emit(self._x_to_sec(e.position().x()))
        self._drag_k = None

    # ── 렌더 ─────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.setBrush(QColor(T.BG_INSET))
        p.setPen(QPen(QColor(T.BORDER_SUBTLE), 1))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 8, 8)
        # 파형(피크) — 격자 아래에 깔림
        if self._peaks:
            mid, amp = h / 2, h / 2 - 12
            pen, faint = QPen(QColor(T.BORDER_DEFAULT), 1), QColor(T.BORDER_DEFAULT)
            faint.setAlpha(140)                 # 코드 인식 끝 이후는 흐리게(음영과 겹침)
            n, span = len(self._peaks), self._wave_t1 - self._wave_t0
            i0 = max(0, int((self._t0 - self._wave_t0) / span * n))
            i1 = min(n, int((self._t1 - self._wave_t0) / span * n) + 1)
            for i in range(i0, i1):            # 곡 전체 피크 중 창 안만
                lo, hi = self._peaks[i]
                t = self._wave_t0 + (i + 0.5) / n * span
                p.setPen(QPen(faint, 1) if self._end is not None and t > self._end else pen)
                x = int(self._sec_to_x(t))
                p.drawLine(x, int(mid - hi * amp), x, int(mid - lo * amp))
        # 자동 인식 비트 — 사용자가 옮겨도 원래 위치를 흐리게 남긴다
        ghost = QColor(T.TEXT_DIM)
        ghost.setAlpha(70)
        p.setPen(QPen(ghost, 1, Qt.PenStyle.DashLine))
        for t in self._ghost:
            if self._t0 <= t <= self._t1:
                x = int(self._sec_to_x(t))
                p.drawLine(x, 4, x, h - 4)
        if self._beat_at is None:
            return
        # 예비박 구간 음영
        if self._lead > 0:
            shade = QColor(T.BORDER_ACTIVE)
            shade.setAlpha(28)
            x0 = self._sec_to_x(self._beat_at(-self._lead * self._beats))
            p.fillRect(QRectF(x0, 1, self._sec_to_x(self._beat_at(0)) - x0, h - 2), shade)
        f = QFont(T.FONT_MONO)
        f.setPixelSize(10)
        p.setFont(f)
        # 창 안의 박(선명)·마디선(진함+번호) — 예비박 마디부터
        i = max(-self._beats * self._lead, math.floor(self._index_at(self._t0)) - 1)
        while True:
            t = self._beat_at(i)
            if t > self._t1:
                break
            if t >= self._t0:
                x = self._sec_to_x(t)
                if i % self._beats == 0:            # 마디선
                    p.setPen(QPen(QColor(T.TEXT_BODY), 2))
                    p.drawLine(int(x), 8, int(x), h - 8)
                    p.setPen(QColor(T.TEXT_MUTED))
                    n = i // self._beats + 1
                    p.drawText(int(x) + 4, 16, f"{n}" if n >= 1 else "예비")
                else:                               # 박 — 마디선과 같은 밝기, 굵기만 얇게
                    p.setPen(QPen(QColor(T.TEXT_BODY), 1))
                    p.drawLine(int(x), 14, int(x), h - 14)
            i += 1
        # 코드 인식 끝 — 이후 음영 + 굵은 핸들
        if self._end is not None and self._end <= self._t1:
            x = self._sec_to_x(self._end)
            dim = QColor(T.BG_BASE)
            dim.setAlpha(150)
            p.fillRect(QRectF(x, 1, w - x, h - 2), dim)
            p.setPen(QPen(QColor(T.BORDER_ACTIVE), 3))
            p.drawLine(int(x), 2, int(x), h - 2)
            p.setPen(QColor(T.BORDER_ACTIVE))
            p.drawText(int(x) - 28, h - 6, "끝")
        # 재생 헤드
        if self._pos is not None and self._t0 <= self._pos <= self._t1:
            x = self._sec_to_x(self._pos)
            p.setPen(QPen(QColor(T.SCRUB_HEAD), 2))
            p.drawLine(int(x), 4, int(x), h - 4)


class BeatScreen(QWidget):
    proceedRequested = pyqtSignal()
    backToLinkRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl = None
        self._model = None
        self.playhead: Playhead | None = None
        # 격자: 검출 비트 모드(_lattice = 보정 비트, 1마디 = _lattice[_bar1] + _offset)
        #      또는 BPM 직접 지정 시 균등 모드(_lattice=None, _u_anchor + i*beat_len)
        self._lattice: list[float] | None = None
        self._bar1 = 0
        self._offset = 0.0
        self._u_anchor = 0.0
        self.beat_len = 0.5      # 박 길이(초) — BPM = 60/beat_len, 격자 밖 연장에도 사용
        self._bpm_text = ""      # BPM 칸에 마지막으로 표시한 값
        self._end_bar: int | None = None   # 코드 인식 끝 마디선(1마디부터 마디 수), None = 곡 끝
        self._dur = ZOOM_SEC
        self._locked = False     # 확인 후 코드 편집 단계
        self._cells: dict[int, QFrame] = {} # bar → 칸(하이라이트용)
        self._drag_start: int | None = None # 칸 드래그 시작 마디
        self._drag_cur: int | None = None   # 드래그 현재 마디
        self._drag_loop = False             # 시작 칸을 벗어나면 루프 모드
        self._step = 1           # 박자 단계: 1 시작점 · 2 끝부분 박자 · 3 예비박
        self.count_in = 1        # 예비박 마디 수
        self._metro_next: int | None = None     # 다음에 예약할 박 번호(anchor 기준)
        self._metro_gen = 0                     # 시킹/정지 시 예약 클릭 무효화
        self._clock = QElapsedTimer()           # 오디오 위치 갱신 사이 보간
        self._clock_pos: float | None = None
        self._clicks = {}                       # 강박/약박 클릭음
        for strong, freq in ((True, METRO_HI_HZ), (False, METRO_LO_HZ)):
            eff = QSoundEffect(self)
            eff.setSource(QUrl.fromLocalFile(render_click_wav(freq)))
            eff.setVolume(0.8)
            self._clicks[strong] = eff

        # 같은 타임라인을 공유하는 박자 조정 / 코드 편집 화면
        content = T.compact_content(self)
        outer = QVBoxLayout(content)
        outer.setContentsMargins(T.PAD_H, T.PAD_V, T.PAD_H, T.PAD_V)
        outer.setSpacing(10)
        self.flow = FlowHeader(2)
        outer.addWidget(self.flow)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages)
        self.beat_page = QWidget()
        self.chord_page = QWidget()
        self.pages.addWidget(self.beat_page)
        self.pages.addWidget(self.chord_page)
        root = QVBoxLayout(self.beat_page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.link_btn = QPushButton("← 링크")
        self.link_btn.setStyleSheet(T.qss_ghost_btn())
        self.link_btn.clicked.connect(self.backToLinkRequested.emit)
        top.addWidget(self.link_btn)
        title = QLabel("박자 조정")
        title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS}';"
            "font-size:18px;font-weight:700;")
        top.addSpacing(8)
        top.addWidget(title)
        top.addStretch(1)
        root.addLayout(top)

        self.warn_lbl = QLabel(
            "비트 검출이 부족해 기본 격자를 사용했습니다. BPM과 시작박을 직접 확인해 주세요.")
        self.warn_lbl.setStyleSheet(f"color:{T.BADGE_OUT};font-size:12px;")
        self.warn_lbl.setWordWrap(True)
        self.warn_lbl.hide()
        root.addWidget(self.warn_lbl)

        # 확대바(1단계: 처음 10초, 2단계: 끝부분)
        for side in ("l", "r"):
            bar = ZoomBar()
            bar.clicked.connect(self._on_zoom_click)
            setattr(self, f"zoom_{side}", bar)
        self.zoom_r.endDragged.connect(self._on_end_drag)  # 끝: 코드 인식 끝 마디
        self.zoom_r.endReleased.connect(self._center_end_window)  # 놓으면 끝선 기준으로 창 이동
        self.zoom_l.barDragged.connect(self._on_drag)      # 시작: 격자 평행이동
        self.zoom_r.barDragged.connect(self._on_stretch)   # 끝: 시작 고정·BPM 조정
        self.zoom_r.pan_bars = False                       # 끝부분 마디선은 선이 마우스를 따라감
        for z in (self.zoom_l, self.zoom_r):
            z.dragStarted.connect(self.pause)              # 끄는 동안 음원·메트로놈 정지
            z.dragFinished.connect(self._play_start)       # 놓으면 스페이스바처럼 재생

        # ── 박자 · BPM ───────────────────────────────────────────
        combo_qss = (
            f"QComboBox{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_BODY};"
            f"border:1px solid {T.BORDER_DEFAULT};border-radius:8px;"
            f"padding:4px 10px;font-family:'{T.FONT_MONO}';font-size:12px;}}"
            f"QComboBox QAbstractItemView{{background:{T.BG_SURFACE_ALT};"
            f"color:{T.TEXT_BODY};selection-background-color:{T.BORDER_DEFAULT};}}")
        self.tempo_row = QWidget()
        ctrl = QHBoxLayout(self.tempo_row)
        ctrl.setContentsMargins(0, 0, 0, 0)
        self.sig_box = QComboBox()
        for sig in ("3/4", "4/4"):
            self.sig_box.addItem(f"박자 {sig}", sig)
        self.sig_box.setCurrentIndex(1)
        self.sig_box.setStyleSheet(combo_qss)
        self.sig_box.currentIndexChanged.connect(lambda _: self._refresh())
        ctrl.addWidget(self.sig_box)
        self.bpm_edit = QLineEdit()   # BPM(간격) 직접 입력 — 드래그로는 안 바뀜
        self.bpm_edit.setFixedWidth(90)
        self.bpm_edit.setAccessibleName("곡 BPM")
        self.bpm_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.bpm_edit.setStyleSheet(
            f"QLineEdit{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_PRIMARY};"
            f"border:1px solid {T.BORDER_DEFAULT};border-radius:8px;"
            f"padding:4px 8px;font-family:'{T.FONT_MONO}';font-size:12px;"
            "font-weight:700;}")
        self.bpm_edit.editingFinished.connect(self._on_bpm_edited)
        self.bpm_edit.returnPressed.connect(self.setFocus)   # Enter → 커서 해제(스페이스=재생)
        ctrl.addSpacing(8)
        ctrl.addWidget(self.bpm_edit)
        bpm_tag = QLabel("BPM")
        bpm_tag.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        ctrl.addWidget(bpm_tag)
        self.auto_bpm_lbl = QLabel()   # 컴퓨터가 검출 비트로 추정한 BPM
        self.auto_bpm_lbl.setStyleSheet(f"color:{T.TEXT_DIM};font-size:12px;")
        ctrl.addSpacing(12)
        ctrl.addWidget(self.auto_bpm_lbl)
        self.reset_btn = QPushButton("자동추정값 초기화")
        self.reset_btn.setStyleSheet(T.qss_ghost_btn())
        self.reset_btn.setToolTip("박자·BPM·격자를 컴퓨터가 추정한 값으로 되돌립니다")
        self.reset_btn.clicked.connect(self._reset_auto)
        ctrl.addSpacing(8)
        ctrl.addWidget(self.reset_btn)
        ctrl.addStretch(1)
        root.insertWidget(1, self.tempo_row)    # '박자 조정' 제목 바로 아래(단계와 무관하게 항상 활성)

        # ── 예비박 마디 수(3단계) ─────────────────────────────────
        self.count_row = QWidget()
        cnt = QHBoxLayout(self.count_row)
        cnt.setContentsMargins(0, 0, 0, 0)
        self.count_minus = QPushButton("−")
        self.count_plus = QPushButton("+")
        self.count_lbl = QLabel()
        self.count_lbl.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_MONO}';font-size:13px;"
            "font-weight:700;")
        for btn, d, name in ((self.count_minus, -1, "예비박 한 마디 줄이기"),
                             (self.count_plus, 1, "예비박 한 마디 늘리기")):
            btn.setStyleSheet(T.qss_ghost_btn())
            btn.setFixedWidth(40)
            btn.setAccessibleName(name)
            btn.clicked.connect(lambda _, d=d: self._set_count_in(self.count_in + d))
        cnt.addWidget(self.count_minus)
        cnt.addWidget(self.count_lbl)
        cnt.addWidget(self.count_plus)
        cnt.addStretch(1)

        # ── 세로 3단계: 현재 단계 아래는 흐리게·비활성(Enter 다음, Backspace 이전) ──
        self.sections: list[QWidget] = []
        self._sec_titles: list[QLabel] = []
        for name, widgets in (("1. 코드시작 선택", (self.zoom_l,)),
                              ("2. 코드종료 선택", (self.zoom_r,)),
                              ("3. 예비박 설정", (self.count_row,))):
            sec = QWidget()
            col = QVBoxLayout(sec)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(6)
            lbl = QLabel(name)
            col.addWidget(lbl)
            for w in widgets:
                col.addWidget(w)
            root.addWidget(sec)
            self.sections.append(sec)
            self._sec_titles.append(lbl)
        # 이전 단계의 UI를 누르면 그 단계로 돌아가고 아랫단계는 다시 비활성
        for step, widgets in ((1, (self.zoom_l,)), (2, (self.zoom_r,))):
            for w in widgets:
                w._beat_step = step
                w.installEventFilter(self)
        root.addStretch(1)

        nav = QHBoxLayout()
        nav.addStretch(1)
        self.next_btn = QPushButton("다음 (Enter)")
        self.next_btn.setStyleSheet(T.qss_primary_btn())
        self.next_btn.clicked.connect(self._advance)
        nav.addWidget(self.next_btn)
        self.confirm_btn = QPushButton("확인 (Enter)")
        self.confirm_btn.setStyleSheet(T.qss_primary_btn())
        self.confirm_btn.setToolTip("변경한 박자를 반영하고 코드 편집으로 이동")
        self.confirm_btn.clicked.connect(self._on_confirm)
        nav.addWidget(self.confirm_btn)
        root.addLayout(nav)
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            QShortcut(QKeySequence(key), self, self._advance,
                      context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        QShortcut(QKeySequence(Qt.Key.Key_Backspace), self,
                  lambda: self._locked or self._show_step(self._step - 1),
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # 스페이스바 = 재생/일시정지(포커스된 버튼 클릭보다 먼저 처리)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self._toggle_play,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

        root = QVBoxLayout(self.chord_page)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        chord_top = QHBoxLayout()
        self.back_to_beat_btn = QPushButton("← 박자 조정")
        self.back_to_beat_btn.setStyleSheet(T.qss_ghost_btn())
        self.back_to_beat_btn.clicked.connect(self._back_to_beat)
        chord_top.addWidget(self.back_to_beat_btn)
        chord_top.addSpacing(8)
        chord_title = QLabel("코드 편집")
        chord_title.setStyleSheet(title.styleSheet())
        chord_top.addWidget(chord_title)
        chord_top.addStretch(1)
        self.key_box = QComboBox()
        for r in range(12):
            for mode, label in (("major", "장조"), ("minor", "단조")):
                self.key_box.addItem(f"키: {pc_name(r)} {label}", f"{pc_name(r)} {mode}")
        self.key_box.setStyleSheet(combo_qss)
        self.key_box.setToolTip("분석된 키를 확인하거나 직접 선택합니다. 코드와 박자는 유지됩니다.")
        self.key_box.currentIndexChanged.connect(self._on_key_changed)
        chord_top.addWidget(self.key_box)
        root.addLayout(chord_top)
        chord_hint = QLabel("분석된 코드를 확인하세요. 칸을 클릭하면 수정, 여러 칸을 드래그하면 루프를 만듭니다. 자동 인식은 장·단 3화음 추정입니다.")
        chord_hint.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        chord_hint.setWordWrap(True)
        root.addWidget(chord_hint)

        # ── 아래: 루프 리스트 + 마디별 코드표(세로 스크롤) ───────
        right = QVBoxLayout()
        right.setSpacing(10)
        loop_row = QHBoxLayout()
        grid_lbl = QLabel("마디별 코드 (클릭=코드 수정 · 드래그=루프 지정)")
        grid_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        loop_row.addWidget(grid_lbl)
        self.loops_row = QHBoxLayout()
        self.loops_row.setSpacing(6)
        self.loops_row.setContentsMargins(0, 0, 0, 0)
        loops_host = QWidget()
        loops_host.setObjectName("loopChips")
        loops_host.setStyleSheet(f"QWidget#loopChips{{background:{T.BG_BASE};}}")
        loops_host.setLayout(self.loops_row)
        self.loops_scroll = QScrollArea()
        self.loops_scroll.setWidgetResizable(True)
        self.loops_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.loops_scroll.setFixedHeight(54)
        self.loops_scroll.setWidget(loops_host)
        loop_row.addSpacing(12)
        loop_row.addWidget(self.loops_scroll, 1)
        self._loop_wrap = QWidget()
        self._loop_wrap.setLayout(loop_row)
        right.addWidget(self._loop_wrap)

        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_scroll.setStyleSheet(
            "QScrollArea{border:none;background:transparent;}"
            "QScrollArea > QWidget > QWidget{background:transparent;}")
        self.holder = QWidget()
        self.holder.setStyleSheet("background:transparent;")
        hwrap = QHBoxLayout(self.holder)      # 표 전체 가운데 정렬
        hwrap.setContentsMargins(0, 0, 0, 0)
        hwrap.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        grid_host = QWidget()
        grid_host.setStyleSheet("background:transparent;")
        self.grid = QGridLayout(grid_host)
        self.grid.setSpacing(8)
        self.grid.setContentsMargins(0, 0, 0, 0)
        hwrap.addStretch(1)
        hwrap.addWidget(grid_host)
        hwrap.addStretch(1)
        self.grid_scroll.setWidget(self.holder)
        right.addWidget(self.grid_scroll, 1)
        root.addLayout(right, 1)

        # ── 조정 완료 → 다음 화면 ────────────────────────────────
        done_row = QHBoxLayout()
        done_row.addStretch(1)
        self.done_btn = QPushButton("리프 확인으로")
        self.done_btn.setStyleSheet(T.qss_primary_btn())
        self.done_btn.clicked.connect(self._on_done)
        done_row.addWidget(self.done_btn)
        done_row.addStretch(1)
        root.addLayout(done_row)

    def showEvent(self, e):
        super().showEvent(e)
        self.setFocus()
        stagger([self.holder, self.done_btn] if self._locked else
                [self.sections[0]])

    # ── 격자 상태 ────────────────────────────────────────────────
    def _beats(self) -> int:
        return int((self.sig_box.currentData() or "4/4").split("/")[0])

    @property
    def bar_len(self) -> float:
        return self._beats() * self.beat_len

    def beat_at(self, i: int) -> float:
        """박 i의 시각(0 = 1마디 첫 박). 검출 비트 범위 밖은 beat_len으로 연장."""
        lat = self._lattice
        if lat is None:
            return self._u_anchor + i * self.beat_len
        j = self._bar1 + i
        if j < 0:
            return lat[0] + self._offset + j * self.beat_len
        if j >= len(lat):
            return lat[-1] + self._offset + (j - len(lat) + 1) * self.beat_len
        return lat[j] + self._offset

    def index_at(self, t: float) -> float:
        """beat_at의 역 — 시각 t의 (분수) 박 번호."""
        lat = self._lattice
        if lat is None:
            return (t - self._u_anchor) / self.beat_len
        u = t - self._offset
        if u < lat[0]:
            j = (u - lat[0]) / self.beat_len
        elif u >= lat[-1]:
            j = len(lat) - 1 + (u - lat[-1]) / self.beat_len
        else:
            k = bisect.bisect_right(lat, u) - 1
            j = k + (u - lat[k]) / (lat[k + 1] - lat[k])
        return j - self._bar1

    @property
    def anchor(self) -> float:
        """1마디 첫 박 시각. 대입 = 격자 평행이동(간격 유지)."""
        return self.beat_at(0)

    @anchor.setter
    def anchor(self, t: float):
        """검출 비트 격자: 1마디 = t에 가장 가까운 비트 + 차이(재진입 시 같은 규칙으로 복원)."""
        lat = self._lattice
        if lat is None:
            self._u_anchor = t
            return
        k = bisect.bisect_left(lat, t)
        self._bar1 = min((j for j in (k - 1, k) if 0 <= j < len(lat)),
                         key=lambda j: abs(lat[j] - t))
        self._offset = t - lat[self._bar1]

    def _to_uniform(self, beat_len: float):
        """BPM 직접 지정 → 균등 격자(1마디 위치 유지)."""
        a = self.anchor
        self._lattice, self._u_anchor, self.beat_len = None, a, beat_len

    def _reset_auto(self):
        """박자·BPM·격자를 자동 추정값으로 — 1마디는 지금 위치에서 가장 가까운 검출 비트."""
        if self.tl is None:
            return
        idx = self.sig_box.findData(self.tl.analysis_info.get("auto_time_sig", self.tl.time_sig))
        self.sig_box.blockSignals(True)
        self.sig_box.setCurrentIndex(idx if idx >= 0 else 1)
        self.sig_box.blockSignals(False)
        lat = self.zoom_l._ghost
        if len(lat) >= 4:
            a = self.anchor
            self._lattice, self.beat_len = lat, (lat[-1] - lat[0]) / (len(lat) - 1)
            self.anchor = a
            self._offset = 0.0
        self._show_bpm()
        self._refresh()

    def _max_count_in(self) -> int:
        """예비박 시작이 음원 앞 EDGE_SEC보다 앞서지 않는 최대 마디 수(최소 1)."""
        n = 1
        while n < 64 and self.beat_at(-(n + 1) * self._beats()) >= -EDGE_SEC - 1e-6:
            n += 1
        return n

    def _refresh(self):
        lead = self.beat_at(-self.count_in * self._beats())
        if lead < -EDGE_SEC:                    # 예비박이 음원 앞 5초 밖이면 격자를 뒤로
            self.anchor = self.anchor + (-EDGE_SEC - lead)
            lead = -EDGE_SEC
        start = min(self.zoom_l._t0, lead)     # 창은 드래그로 따라가고, 예비박이 넘치면 왼쪽으로
        self.zoom_l.set_window(start, start + ZOOM_SEC)   # 끝부분 창과 같은 10초 축척
        for z in (self.zoom_l, self.zoom_r):
            z.set_grid(self.beat_at, self.index_at, self._beats(), self.count_in)
            z.set_end(self._end_time())
        self.count_lbl.setText(f"예비박 {self.count_in}마디")
        self.count_minus.setEnabled(self.count_in > 1)
        self.count_plus.setEnabled(self.count_in < self._max_count_in())

    def _end_time(self) -> float:
        """코드 인식 끝 시각 — 지정 마디선 또는 곡 끝."""
        return self._dur if self._end_bar is None else self.beat_at(self._end_bar * self._beats())

    def _center_end_window(self):
        """끝부분 창 = 끝선이 처음 자리(창 가운데)에 오도록.

        창은 처음 창과 같은 10초, 음원 끝 + EDGE_SEC를 넘지 않는다.
        """
        r0 = max(0.0, min(self._end_time() - EDGE_SEC, self._dur + EDGE_SEC - ZOOM_SEC))
        self.zoom_r.set_window(r0, r0 + ZOOM_SEC)

    def _on_end_drag(self, sec: float):
        """끝 핸들 → 가장 가까운 마디선(1마디 이후, 음원 끝 + EDGE_SEC 이내)."""
        m = max(1, round(self.index_at(sec) / self._beats()))
        while m > 1 and self.beat_at(m * self._beats()) > self._dur + EDGE_SEC:
            m -= 1
        self._end_bar = m
        self._refresh()

    def _set_count_in(self, n: int):
        """예비박은 최소 1마디 — 시작이 −10초를 넘지 않는 만큼까지."""
        self.count_in = max(1, min(n, self._max_count_in()))
        self._refresh()

    # ── 단계(1 코드시작 · 2 코드종료 · 3 예비박) ───────────────────
    def _show_step(self, step: int):
        """현재 단계까지 활성, 아랫단계는 흐리게·비활성(값은 유지)."""
        self._step = max(1, min(3, step))
        self.pause()
        for i, (sec, lbl) in enumerate(zip(self.sections, self._sec_titles), 1):
            self._dim(sec, i > self._step)
            lbl.setStyleSheet(
                f"color:{T.TEXT_PRIMARY if i == self._step else T.TEXT_MUTED};"
                f"font-size:{15 if i == self._step else 13}px;font-weight:700;")
        self.zoom_r.end_draggable = True
        self.next_btn.setVisible(self._step < 3)
        self.confirm_btn.setVisible(self._step == 3)
        self._refresh()

    def _advance(self):
        """Enter: 다음 단계, 마지막 단계면 확인(코드 편집으로). BPM 칸에선 적용만."""
        if self._locked:
            return
        if self.bpm_edit.hasFocus():       # BPM 입력 중 Enter = 적용하고 커서 해제
            self._on_bpm_edited()
            self.setFocus()
            return
        if self._step < 3:
            self._show_step(self._step + 1)
        else:
            self._on_confirm()

    def eventFilter(self, obj, e):
        """이전 단계 UI를 누르거나 포커스하면 그 단계로 — 아랫단계는 다시 비활성."""
        step = getattr(obj, "_beat_step", None)
        touched = (e.type() == QEvent.Type.MouseButtonPress or (   # 창 전환 포커스는 제외
            e.type() == QEvent.Type.FocusIn and e.reason() in (
                Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)))
        if step is not None and step < self._step and not self._locked and touched:
            self._show_step(step)
        return super().eventFilter(obj, e)

    # ── 로드 ─────────────────────────────────────────────────────
    def set_timeline(self, tl, model=None):
        if self.playhead:
            self.playhead.pause()
        self.tl = tl
        self.warn_lbl.setVisible(tl.analysis_info.get("beat_detected") is False)
        self._model = model
        mode = "minor" if "minor" in (tl.key or "").lower() else "major"
        self.key_box.blockSignals(True)
        self.key_box.setCurrentIndex(self.key_box.findData(f"{pc_name(tl.key_root)} {mode}"))
        self.key_box.blockSignals(False)
        self._dur = (tl.bar_times[-1] if tl.bar_times else tl.total_sec()) or ZOOM_SEC
        idx = self.sig_box.findData(tl.time_sig)
        self.sig_box.blockSignals(True)
        self.sig_box.setCurrentIndex(idx if idx >= 0 else 1)
        self.sig_box.blockSignals(False)
        self.zoom_l.set_window(0.0, ZOOM_SEC)
        self._wav = getattr(tl, "wav_ref", "")
        self._wav_level = _wave_level(self._wav)   # 곡마다 파형 크기를 비슷하게(진입 시 1회)
        peaks = _wave_peaks(self._wav, 0.0, self._dur, level=self._wav_level,
                            buckets=round(WAVE_BUCKETS * self._dur / ZOOM_SEC))
        for z in (self.zoom_l, self.zoom_r):
            z.set_wave(peaks, 0.0, self._dur)   # 곡 전체 1회 — 창을 끌어도 다시 읽지 않음
        lat = (tl.smoothed_beats() if tl.analysis_info.get("beat_detected") is not False
               else [])
        for z in (self.zoom_l, self.zoom_r):
            z.set_ghost(lat)                    # 흐린 선 = 보정한 검출 비트
        bar0 = tl.bar_times[0] if tl.bar_times else 0.0
        auto_len = (lat[-1] - lat[0]) / (len(lat) - 1) if len(lat) >= 4 else None
        self.auto_bpm_lbl.setText(f"자동 추정 {60.0 / auto_len:.1f} BPM" if auto_len
                                  else "자동 추정 없음(비트 검출 부족)")
        tl.analysis_info.setdefault("auto_time_sig", tl.time_sig)   # 초기화 기준(분석 박자)
        self.reset_btn.setEnabled(bool(auto_len))
        if auto_len and not tl.timing_override:
            # 검출 비트 격자: 1마디 = 분석 첫 마디선에 가장 가까운 비트(처음엔 점선과 일치)
            self._lattice, self.beat_len = lat, auto_len
            self.anchor = bar0
            if not tl.grid_confirmed:
                self._offset = 0.0              # 분석 직후: 점선 비트에 정확히
        else:                                   # BPM으로 확정했던 세션·비트 없음 → 균등
            self._lattice, self._u_anchor, self.beat_len = None, bar0, tl.beat_sec()
        self._end_bar = (None if tl.chord_end is None else
                         max(1, round(self.index_at(tl.chord_end) / self._beats())))
        self._center_end_window()
        self._show_bpm()
        self.count_in = max(1, tl.count_in_bars)
        self.playhead = Playhead(self._dur, tl.audio_ref, self)
        self.playhead.positionChanged.connect(self._on_tick)
        self._set_locked(False)
        self._reset_drag()
        self._show_step(1)
        self._build_grid()
        self._build_loops()

    def pause(self):
        if self.playhead:
            self._metro_reset()
            self.playhead.pause()

    # ── 드래그 = 격자 평행이동(BPM 불변, 재격자화는 확정 시) ────
    def _on_drag(self, k: int, sec: float):
        """마디 k 선을 sec로 — 격자 평행이동(간격 유지). 검출 비트에 붙으면 그 비트가 마디선."""
        sec, j = self._snap(sec, self.zoom_l)
        if j is not None and self._lattice is not None:
            self._bar1, self._offset = j - k * self._beats(), 0.0
        else:
            self.anchor = self.anchor + sec - self.beat_at(k * self._beats())
        if self.anchor > self._dur:             # 1마디는 음원 안에서
            self.anchor = self._dur
        self._refresh()

    def _on_zoom_click(self, sec: float):
        """1단계: 클릭한 곳 = 1마디(재생은 스페이스바)."""
        if self._step == 1:
            self._on_drag(0, sec)

    def _snap(self, sec: float, zoom: ZoomBar) -> tuple[float, int | None]:
        """보정 비트 SNAP_PX 이내면 (그 비트 시각, 비트 번호) — 자석처럼 붙는다."""
        beats = zoom._ghost
        if not beats:
            return sec, None
        j = min(range(len(beats)), key=lambda k: abs(beats[k] - sec))
        tol = SNAP_PX * (zoom._t1 - zoom._t0) / max(1, zoom.width())
        return (beats[j], j) if abs(beats[j] - sec) <= tol else (sec, None)

    def _on_stretch(self, k: int, sec: float):
        """끝부분 마디 k 선을 sec로 — 시작박 고정, 균등 격자로 간격(BPM)을 바꾼다."""
        sec, _ = self._snap(sec, self.zoom_r)
        if k < 1 or sec <= self.anchor:
            return
        bpm = max(20.0, min(400.0, 60.0 * self._beats() * k / (sec - self.anchor)))
        self._to_uniform(60.0 / bpm)
        self._show_bpm()
        self._refresh()

    def _play_from(self, sec: float):
        if self.playhead:
            self.playhead.seek(sec)
            self._metro_reset()
            self._metro_next = math.ceil(self.index_at(sec) - 1e-6)   # 시작 박도 클릭
            self.playhead.play()

    def _toggle_play(self):
        """스페이스바: 재생 중이면 정지, 아니면 1마디부터(2단계는 끝부분 창의 첫 마디부터)."""
        if not self.playhead:
            return
        if self.playhead.is_playing():
            self.pause()
            return
        self._play_start()

    def _play_start(self):
        """1마디부터 재생(2단계는 끝부분 창의 첫 마디부터)."""
        if not self.playhead:
            return
        bar = 0
        if self._step == 2:
            bar = math.ceil(self.index_at(self.zoom_r._t0) / self._beats() - 1e-6)
        self._play_from(self.beat_at(bar * self._beats()))

    def _on_bpm_edited(self):
        """BPM(간격) 직접 입력 — 정수 또는 .5로 맞추고, 시작박 유지·균등 격자로 전환."""
        if self.bpm_edit.text() == self._bpm_text:
            return    # 표시값 그대로(포커스 이동 등) — 검출 비트 격자를 균등 격자로 바꾸지 않게
        try:
            bpm = float(self.bpm_edit.text())
        except ValueError:
            self._show_bpm()
            return
        bpm = max(20.0, min(400.0, bpm))
        self._to_uniform(60.0 / bpm)
        self._show_bpm()
        self._refresh()

    def _show_bpm(self):
        """BPM 칸 표시(정수 또는 .5) — 표시한 글자를 기억해 '그대로인지' 판단에 쓴다."""
        self._bpm_text = f"{60.0 / self.beat_len:.1f}"
        self.bpm_edit.setText(self._bpm_text)

    # ── 재생 ─────────────────────────────────────────────────────
    def _on_tick(self, sec: float):
        self.zoom_l.set_position(sec)
        self.zoom_r.set_position(sec)
        self._metronome(self._smooth(sec))

    def _smooth(self, sec: float) -> float:
        """오디오 위치는 ~90ms 단위로만 갱신된다 → 마지막 갱신 이후 경과 시간으로 보간.

        재생 시작 직후처럼 위치가 오래 멈춰 있으면 소리보다 앞서가지 않게 0.12초까지만.
        """
        if sec != self._clock_pos:
            self._clock_pos = sec
            self._clock.restart()
            return sec
        if self.playhead and self.playhead.is_playing():
            return sec + min(0.12, self._clock.elapsed() / 1000.0) * self.playhead.rate
        return sec

    def _metro_reset(self):
        """시킹·재생 전환 시 예약된 클릭 무효화 — 다음 틱에 현재 위치부터 다시 예약."""
        self._metro_gen += 1
        self._metro_next = None
        self._clock_pos = None

    def _metronome(self, est: float):
        """다음 박(번호 단조 증가)을 정확한 시각에 한 번만 예약 — 틱 지터로 두 번 울리지 않음.

        ponytail: QTimer 예약 + QSoundEffect 출력 지연(수십 ms 이내). 샘플 정확도가
        필요하면 오디오에 클릭을 믹스해 재생으로.
        """
        if not (self.playhead and self.playhead.is_playing()):
            return
        if self.zoom_l.dragging or self.zoom_r.dragging:   # 드래그 중엔 무음
            self._metro_gen += 1
            self._metro_next = None
            return
        n = self._metro_next
        # 첫 예약·큰 점프·격자 변경(드래그/BPM) → 현재 위치 다음 박부터 다시
        if n is None or not -0.2 < self.beat_at(n) - est < self.beat_len + METRO_AHEAD:
            n = math.ceil(self.index_at(est) - 1e-6)
        while self.beat_at(n) <= est + METRO_AHEAD:
            self._schedule_click(max(0.0, self.beat_at(n) - est), n % self._beats() == 0)
            n += 1
        self._metro_next = n

    def _schedule_click(self, delay: float, strong: bool):
        gen = self._metro_gen
        QTimer.singleShot(round(delay * 1000),
                          lambda: gen == self._metro_gen and self._clicks[strong].play())

    def _bar_list(self) -> list[float]:
        """화면 격자의 마디 시작 목록(1마디부터, 곡 끝 전까지)."""
        bars, m = [], 0
        while (t := self.beat_at(m * self._beats())) < self._dur - 1e-3:
            bars.append(t)
            m += 1
        return bars

    def _apply(self, then=None):
        """격자 적용 — 재생 멈추고 화면 격자 그대로 재격자화(아래 코드 목록 갱신).

        마디선·박자가 그대로면 재적용하지 않는다(코드 수동 수정 보존).
        원자료 없는 구 캐시는 격자만 유지한 채 통과. 끝나면 then()을 부른다.
        """
        self.pause()
        then = then or (lambda: None)
        if self.tl is None:
            return then()
        bars, sig = self._bar_list(), self.sig_box.currentData() or self.tl.time_sig
        end = None if self._end_bar is None else self._end_time()
        old = self.tl.bar_times[:-1]
        if (sig == self.tl.time_sig and len(bars) == len(old) and end == self.tl.chord_end
                and all(abs(a - b) < 1e-4 for a, b in zip(bars, old))):
            return then()
        self.tl.time_sig = sig
        self.tl.chord_end = end
        self.tl.bpm = 60.0 / self.beat_len      # 반올림 없이 — 예비박 길이가 화면과 같게
        self.tl.timing_override = self._lattice is None   # 검출 비트 격자면 박도 검출 비트

        def done(ok):
            if ok:
                self._build_grid()
            then()
        run_busy(self, lambda: regrid_timeline(self.tl, self._model, bars=bars), done)

    @staticmethod
    def _dim(w: QWidget, dim: bool):
        w.setEnabled(not dim)
        if dim:
            eff = QGraphicsOpacityEffect(w)
            eff.setOpacity(0.35)
            w.setGraphicsEffect(eff)
        else:
            w.setGraphicsEffect(None)

    def _set_locked(self, locked: bool):
        """확정 상태 토글 — 확정 전엔 코드표가, 확정 후엔 박자 편집부가 잠긴다."""
        self._locked = locked
        self.flow.set_stage(3 if locked else 2)
        for w in (self.zoom_l, self.zoom_r, self.sig_box, self.bpm_edit):
            self._dim(w, locked)
        for w in (self._loop_wrap, self.holder):   # 미확정 격자의 코드표는 잠금
            self._dim(w, not locked)
        self.pages.setCurrentWidget(self.chord_page if locked else self.beat_page)
        if not locked:
            self._reset_drag()       # 박자 재편집 → 루프 드래그 중단

    def _on_confirm(self):
        self._on_bpm_edited()
        self._apply(self._finish_confirm)

    def _finish_confirm(self):
        if self.tl is not None:
            self.tl.count_in_bars = self.count_in
            self.tl.grid_confirmed = True
        self._set_locked(True)

    def _back_to_beat(self):
        self.pause()
        self._set_locked(False)
        self._show_step(1)

    def _on_done(self):
        if not self._locked:
            self._apply(self.proceedRequested.emit)   # 미확정 조정이 있으면 반영하고 진행
        else:
            self.proceedRequested.emit()

    # ── 마디별 코드 목록(악보 화면에서 이식, §1 수동 수정) ──────
    def _build_grid(self):
        self._cells = {}
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not self.tl or not self.tl.segments:
            return
        total = self.tl.total_bars()
        prev_seg = None
        last_row = 0
        for bar in range(total):    # 예비박은 코드표에 넣지 않는다
            seg = self.tl.segment_for_bar(bar)
            cell = self._make_cell(bar, seg, seg is not prev_seg)
            last_row = bar // BARS_PER_ROW
            self.grid.addWidget(cell, last_row, bar % BARS_PER_ROW)
            prev_seg = seg
        self.grid.setRowStretch(last_row + 1, 1)

    def _make_cell(self, bar: int, seg, is_new_chord: bool) -> QWidget:
        detour = bool(seg and seg.is_detour)   # 비다이아토닉(§3) — 빨강으로만 표시
        chord_txt = (seg.chord.name if is_new_chord else "／") if seg else ""
        # 종류만(근음 생략). 반복 마디(／)엔 스케일도 생략
        scale_txt = seg.scale.kind if (seg and seg.scale and is_new_chord) else ""

        cell = QFrame()
        cell.setObjectName("barCell")           # 선택자 한정 — 안쪽 QLabel(⊂QFrame)엔 미적용
        if detour:                              # 비다이아토닉 → 빨강 강조
            border, bg = T.BADGE_OUT, T.BG_SURFACE
        else:
            border, bg = T.BORDER_DEFAULT, T.BG_INSET
        cell._base_qss = (
            f"QFrame#barCell{{background:{bg};border:1px solid {border};border-radius:8px;}}"
            f"QFrame#barCell:hover{{background:{T.BG_SURFACE_ALT};border-color:{T.TEXT_MUTED};}}")
        cell._hl_qss = (                        # 루프 지정 선택/범위 하이라이트
            f"QFrame#barCell{{background:{T.BG_SURFACE_ALT};"
            f"border:2px solid {T.BORDER_ACTIVE};border-radius:8px;}}")
        cell.setStyleSheet(cell._base_qss)
        cell.setFixedSize(CELL_W, 60)
        v = QVBoxLayout(cell); v.setContentsMargins(4, 5, 4, 5); v.setSpacing(1)
        center = Qt.AlignmentFlag.AlignHCenter
        bar_lbl = QLabel(f"{bar + 1}")
        bar_lbl.setAlignment(center)
        bar_lbl.setStyleSheet(
            f"color:{T.BADGE_OUT if detour else T.TEXT_DIM};"
            f"font-family:'{T.FONT_MONO}';font-size:9px;border:none;")
        v.addWidget(bar_lbl)
        c = QLabel(chord_txt)
        c.setAlignment(center)
        c.setStyleSheet(
            f"color:{T.TEXT_PRIMARY if is_new_chord else T.TEXT_DIM};"
            f"font-family:'{T.FONT_SANS_EN}';font-size:16px;font-weight:700;border:none;")
        v.addWidget(c)
        s = QLabel(scale_txt)
        s.setAlignment(center)
        s.setStyleSheet(
            f"color:{T.BADGE_OUT if detour else T.TEXT_MUTED};"
            f"font-family:'{T.FONT_MONO}';font-size:10px;border:none;")
        v.addWidget(s)

        if seg is not None:        # 클릭=코드 수정 / 드래그=루프 지정
            cell.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            cell.mousePressEvent = lambda e, b=bar: self._loop_press(b)
            cell.mouseMoveEvent = lambda e: self._loop_drag_to(
                self._bar_at_global(e.globalPosition().toPoint()))
            cell.mouseReleaseEvent = lambda e, sg=seg: self._loop_release(sg)
        self._cells[bar] = cell
        return cell

    def _is_diatonic_name(self, name: str) -> bool:
        """코드 구성음이 전부 현재 키 스케일 안이면 다이아토닉."""
        mode = "minor" if "minor" in (self.tl.key or "").lower() else "major"
        home = set(scale_pcs(self.tl.key_root, mode))
        return all(pc in home for pc in parse_chord(name).chord_tones())

    def _edit_chord(self, seg, bar=None):
        """코드박스 클릭 → 그 자리에서 바로 선택 리스트(루트 ▸ 종류).

        다이아토닉 코드는 굵게 강조만(별도 창·섹션 없음).
        """
        cur = seg.chord.name
        menu = QMenu(self)
        qss = (f"QMenu{{background:{T.BG_SURFACE};color:{T.TEXT_BODY};"
               f"border:1px solid {T.BORDER_DEFAULT};}}"
               f"QMenu::item:selected{{background:{T.BORDER_DEFAULT};"
               f"color:{T.TEXT_PRIMARY};}}")
        menu.setStyleSheet(qss)
        for r in range(12):
            root = pc_name(r)
            sub = menu.addMenu(root)
            sub.setStyleSheet(qss)
            root_dia = False
            for suf in _EDIT_SUFFIXES:
                nm = root + suf
                act = sub.addAction(nm + ("  ●" if nm == cur else ""))
                if self._is_diatonic_name(nm):     # 다이아토닉 → 굵게 강조
                    root_dia = True
                    f = act.font(); f.setBold(True); act.setFont(f)
                act.triggered.connect(
                    lambda _, n=nm, sg=seg, b=bar:
                        n != sg.chord.name and self._apply_chord(sg, n, b))
            if root_dia:                           # 스케일 안 루트도 굵게
                f = sub.menuAction().font(); f.setBold(True)
                sub.menuAction().setFont(f)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(QCursor.pos())

    def _set_chord_harmony(self, seg, chord):
        """현재 키에 맞춰 코드의 스케일과 도수를 갱신(시간/마디는 유지)."""
        key_root = self.tl.key_root
        key_mode = "minor" if "minor" in (self.tl.key or "").lower() else "major"
        home = set(scale_pcs(key_root, key_mode))
        is_detour = not all(pc in home for pc in chord.chord_tones())
        note_set = (sorted(set(chord.chord_scale()) | set(chord.chord_tones()))
                    if is_detour else sorted(home))
        o = diatonic_option(chord, key_root, key_mode, is_detour, note_set)
        seg.chord = chord
        seg.candidates = [ScaleOption(o["kind"], o["root"], o["name"], o["note_set"])]
        seg.degree = degree_for(chord, key_root)
        seg.is_detour = is_detour

    def _on_key_changed(self, index: int):
        if self.tl is None or index < 0:
            return
        key = self.key_box.currentData()
        if key == self.tl.key:
            return
        self.pause()
        self.tl.key = key
        self.tl.key_root = index // 2
        self.tl.key_override = True
        for seg in self.tl.segments:
            self._set_chord_harmony(seg, seg.chord)
        self.tl.available_scales = list(dict.fromkeys(
            seg.scale.kind for seg in self.tl.segments if seg.scale))
        run_busy(self, lambda: bake_examples(self.tl, self._model), lambda _: self._build_grid())

    def _apply_chord(self, seg, name: str, bar=None):
        """수동 선택 코드로 구간의 코드·스케일·리프를 재계산."""
        from build.real_builder import apply_chord_edit
        start, end = seg.start_sec, seg.end_sec
        if bar is not None and len(self.tl.bar_times) > bar + 1:
            start = max(start, self.tl.bar_times[bar])
            end = min(end, self.tl.bar_times[bar + 1])
        run_busy(self, lambda: apply_chord_edit(self.tl, start, end, name, self._model),
                 lambda _: self._build_grid())

    # ── 사용자 루프(§6): 칸 클릭=코드 수정 · 칸 드래그=루프 지정 ──
    def _bar_at_global(self, gp) -> int | None:
        """글로벌 좌표 아래의 마디 칸 — 드래그가 어느 칸 위인지 판정."""
        for b, c in self._cells.items():
            try:
                if c.rect().contains(c.mapFromGlobal(gp)):
                    return b
            except RuntimeError:      # 재격자화로 이미 삭제된 칸
                pass
        return None

    def _loop_press(self, bar: int):
        self._drag_start = bar
        self._drag_cur = bar
        self._drag_loop = False

    def _loop_drag_to(self, bar: int | None):
        if self._drag_start is None or bar is None or bar < 0:
            return
        if bar != self._drag_start or self._drag_loop:
            self._drag_loop = True    # 시작 칸을 벗어나면 루프 모드(복귀=1마디)
            self._drag_cur = bar
            self._update_loop_highlight()

    def _loop_release(self, seg=None):
        start, cur, was_loop = self._drag_start, self._drag_cur, self._drag_loop
        self._reset_drag()
        if start is None:
            return
        if was_loop:                                # 드래그 → 루프 이름 입력
            s, e = sorted((start, cur))
            # 모달을 mouse 이벤트 안에서 바로 열면 재진입 크래시 —
            # 이벤트가 끝난 뒤에 연다.
            QTimer.singleShot(0, lambda: self._ask_loop_name(s, e))
        elif seg is not None:                       # 제자리 클릭 → 코드 수정
            parts = [s for s in self.tl.segments if s.start_bar <= start < s.end_bar]
            if len(parts) > 1:
                menu = QMenu(self)
                for part in parts:
                    action = menu.addAction(f"{part.chord.name} · {part.start_sec:.2f}–{part.end_sec:.2f}초")
                    action.triggered.connect(lambda _, p=part, b=start: self._edit_chord(p, b))
                menu.aboutToHide.connect(menu.deleteLater)
                menu.popup(QCursor.pos())
            else:
                self._edit_chord(seg, start)

    def _highlight_bars(self) -> set[int]:
        if not self._drag_loop or self._drag_start is None:
            return set()
        a, b = sorted((self._drag_start, self._drag_cur))
        return set(range(a, b + 1))                 # 드래그 범위 미리보기

    def _update_loop_highlight(self):
        hl = self._highlight_bars()
        for bar, cell in self._cells.items():
            try:
                cell.setStyleSheet(cell._hl_qss if bar in hl else cell._base_qss)
            except RuntimeError:      # 재격자화로 이미 삭제된 칸
                pass

    def _reset_drag(self):
        self._drag_start = None
        self._drag_cur = None
        self._drag_loop = False
        self._update_loop_highlight()

    def _ask_loop_name(self, s: int, e: int):
        name, ok = QInputDialog.getText(
            self, "루프 정의", f"루프정의: {s + 1}–{e + 1}마디 이름:",
            text=f"루프 {len(self.tl.loops) + 1}")
        if ok and name.strip():
            self.tl.loops.append({"name": name.strip(), "start_bar": s,
                                  "end_bar": e, "on": True})
            if len(self.tl.bar_times) > e + 1:
                self.tl.loops[-1].update(start_sec=self.tl.bar_times[s], end_sec=self.tl.bar_times[e + 1])
            self._build_loops()

    def _build_loops(self):
        while self.loops_row.count():
            it = self.loops_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, lp in enumerate(self.tl.loops if self.tl else []):
            chip = QPushButton(
                f"{lp['name']}  {lp['start_bar'] + 1}–{lp['end_bar'] + 1}마디  ✕")
            chip.setToolTip(f"{lp['name']} · 클릭하면 삭제")
            chip.setMaximumWidth(240)
            chip.setText(chip.fontMetrics().elidedText(chip.text(), Qt.TextElideMode.ElideRight, 210))
            chip.setStyleSheet(T.qss_ghost_btn())
            chip.clicked.connect(lambda _, k=i: self._del_loop(k))
            self.loops_row.addWidget(chip)

    def _del_loop(self, i: int):
        if self.tl and 0 <= i < len(self.tl.loops):
            del self.tl.loops[i]
            self._build_loops()
