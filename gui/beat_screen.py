"""[2a] 박자 조정 화면 (§3.5 2차) — 분석 직후 마디선/BPM 확정.

마스터-디테일: 좌측(고정) = 격자 편집(확대바 2개·박자·BPM·확정·조정완료),
우측(스크롤) = 마디별 코드표.
- 두 확대바 모두 마디선 드래그 = 격자 평행이동(BPM 불변), 놓으면 그 위치부터
  재생. BPM(간격)은 직접 입력으로만 수정. 확정 시에만 재격자화(regrid).
- 코드표 직접 조작: 칸 클릭 = 코드 수정, 칸 드래그 = 루프 지정(놓으면 이름 입력).
"""
from __future__ import annotations

import wave
from array import array

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QLineEdit, QScrollArea, QInputDialog, QFrame,
    QGraphicsOpacityEffect, QMenu
)
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QCursor
from PyQt6.QtCore import Qt, QRectF, pyqtSignal, QTimer

from gui import theme as T
from gui.anim import stagger
from analyze.theory import (
    parse_chord, scale_pcs, degree_for, diatonic_option, pc_name,
)
from player.timeline import ScaleOption
from player.playhead import Playhead
from ml.real_builder import regrid_timeline
from ml.generate import bake_segment

ZOOM_SEC = 10.0      # 확대 창 길이
WAVE_BUCKETS = 300   # 확대 창 파형 해상도(컬럼 수)
BARS_PER_ROW = 8
CELL_W = 86          # 마디 칸 폭
# 수동 코드 수정 선택지(접미사). parse_chord가 인식하는 표기.
_EDIT_SUFFIXES = ["", "m", "7", "maj7", "m7", "m7b5", "dim", "6", "m6", "sus4"]


def _wave_peaks(path: str, t0: float, t1: float,
                buckets: int = WAVE_BUCKETS) -> list[tuple[float, float]]:
    """분석 WAV(PCM16 모노)의 [t0,t1) 구간 min/max 피크. 실패 시 [](파형 생략)."""
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
            samples = array("h", f.readframes(b - a))
        if ch > 1:
            samples = samples[::ch]
        step = max(1, len(samples) // buckets)
        return [(min(c) / 32768.0, max(c) / 32768.0)
                for i in range(0, len(samples), step)
                if (c := samples[i:i + step])][:buckets]
    except (OSError, wave.Error, EOFError):
        return []


class ZoomBar(QWidget):
    """확대 재생바 — 구간의 마디/박/분할 격자 + 재생 헤드. 마디선 드래그 가능."""
    barDragged = pyqtSignal(int, float)   # (전역 마디 인덱스 k, 드래그 위치 초)
    dragFinished = pyqtSignal(int)        # 드래그 종료(마디 인덱스 k) → 해당 위치 재생

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(96)
        self._t0, self._t1 = 0.0, ZOOM_SEC
        self._anchor, self._bar_len, self._beats = 0.0, 2.0, 4
        self._pos = -1.0
        self._drag_k: int | None = None
        self._peaks: list[tuple[float, float]] = []

    def set_window(self, t0: float, t1: float):
        self._t0, self._t1 = t0, max(t1, t0 + 0.1)
        self.update()

    def set_grid(self, anchor: float, bar_len: float, beats: int):
        self._anchor, self._bar_len, self._beats = anchor, bar_len, beats
        self.update()

    def set_position(self, sec: float):
        self._pos = sec
        self.update()

    def set_wave(self, peaks: list[tuple[float, float]]):
        self._peaks = peaks
        self.update()

    # ── 좌표 변환 ────────────────────────────────────────────────
    def _sec_to_x(self, sec: float) -> float:
        return (sec - self._t0) / (self._t1 - self._t0) * self.width()

    def _x_to_sec(self, x: float) -> float:
        return self._t0 + x / max(1, self.width()) * (self._t1 - self._t0)

    # ── 마디선 드래그: 누른 곳에서 가장 가까운 마디선을 잡아 이동 ──
    def mousePressEvent(self, e):
        if self._bar_len <= 0:
            return
        sec = self._x_to_sec(e.position().x())
        self._drag_k = max(0, round((sec - self._anchor) / self._bar_len))

    def mouseMoveEvent(self, e):
        if self._drag_k is not None:
            self.barDragged.emit(self._drag_k, self._x_to_sec(e.position().x()))

    def mouseReleaseEvent(self, e):
        if self._drag_k is not None:
            self.dragFinished.emit(self._drag_k)   # 놓은 자리부터 재생
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
            bw = w / len(self._peaks)
            p.setPen(QPen(QColor(T.BORDER_DEFAULT), 1))
            for i, (lo, hi) in enumerate(self._peaks):
                x = int((i + 0.5) * bw)
                p.drawLine(x, int(mid - hi * amp), x, int(mid - lo * amp))
        if self._bar_len <= 0:
            return
        beat_len = self._bar_len / max(1, self._beats)
        f = QFont(T.FONT_MONO)
        f.setPixelSize(10)
        p.setFont(f)
        # 창 안의 박(선명)·마디선(진함+번호)
        i = max(0, int((self._t0 - self._anchor) / beat_len) - 1)
        while True:
            t = self._anchor + i * beat_len
            if t > self._t1:
                break
            if t >= self._t0:
                x = self._sec_to_x(t)
                if i % self._beats == 0:            # 마디선
                    p.setPen(QPen(QColor(T.TEXT_BODY), 2))
                    p.drawLine(int(x), 8, int(x), h - 8)
                    p.setPen(QColor(T.TEXT_MUTED))
                    p.drawText(int(x) + 4, 16, f"{i // self._beats + 1}")
                else:                               # 박 — 마디선과 같은 밝기, 굵기만 얇게
                    p.setPen(QPen(QColor(T.TEXT_BODY), 1))
                    p.drawLine(int(x), 14, int(x), h - 14)
            i += 1
        # 재생 헤드
        if self._t0 <= self._pos <= self._t1:
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
        self.anchor = 0.0        # 첫 마디선(초)
        self.beat_len = 0.5      # 박 길이(초) — BPM = 60/beat_len
        self._dur = ZOOM_SEC
        self._applied = None     # 마지막 적용 격자(중복 재격자화 방지)
        self._locked = False     # 확정 후 편집 잠금(확정 ↔ 수정 토글)
        self._cells: dict[int, QFrame] = {} # bar → 칸(하이라이트용)
        self._drag_start: int | None = None # 칸 드래그 시작 마디
        self._drag_cur: int | None = None   # 드래그 현재 마디
        self._drag_loop = False             # 시작 칸을 벗어나면 루프 모드

        # 마스터-디테일: 좌(격자 편집·고정) / 우(마디별 코드표·스크롤)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(T.PAD_H, T.PAD_V, T.PAD_H, T.PAD_V)
        outer.setSpacing(24)
        root = QVBoxLayout()      # 좌측 마스터 패널
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

        self.hint_lbl = QLabel(
            "마디선을 드래그하면 격자 전체가 함께 이동하고(BPM 불변), 놓으면 "
            "그 위치부터 재생됩니다. 확정하면 오른쪽 코드표가 새 격자로 "
            "갱신되며 열립니다 — 칸 클릭=코드 수정, 칸 드래그=루프 지정.")
        self.hint_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        self.hint_lbl.setWordWrap(True)
        root.addWidget(self.hint_lbl)

        # 확대바 두 개를 위아래로 쌓음(처음 10초 아래 마지막 10초)
        edit_col = QVBoxLayout()
        edit_col.setSpacing(4)
        for side, cap in (("l", "처음 10초 — 시작박"), ("r", "마지막 10초 — 끝박")):
            lbl = QLabel(cap)
            lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:11px;")
            edit_col.addWidget(lbl)
            bar = ZoomBar()
            bar.barDragged.connect(self._on_drag)          # 양쪽 모두 격자 평행이동
            bar.dragFinished.connect(self._on_drag_end)    # 놓으면 그 위치부터 재생
            edit_col.addWidget(bar)
            setattr(self, f"zoom_{side}", bar)

        # ── 편집기 바로 아래: 박자 · BPM · 시작초 · 확정(재생 멈춤+격자 적용) ──
        combo_qss = (
            f"QComboBox{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_BODY};"
            f"border:1px solid {T.BORDER_DEFAULT};border-radius:8px;"
            f"padding:4px 10px;font-family:'{T.FONT_MONO}';font-size:12px;}}"
            f"QComboBox QAbstractItemView{{background:{T.BG_SURFACE_ALT};"
            f"color:{T.TEXT_BODY};selection-background-color:{T.BORDER_DEFAULT};}}")
        ctrl = QHBoxLayout()
        self.sig_box = QComboBox()
        for sig in ("3/4", "4/4"):
            self.sig_box.addItem(f"박자 {sig}", sig)
        self.sig_box.setCurrentIndex(1)
        self.sig_box.setStyleSheet(combo_qss)
        self.sig_box.currentIndexChanged.connect(lambda _: self._refresh())
        ctrl.addWidget(self.sig_box)
        self.bpm_edit = QLineEdit()   # BPM(간격) 직접 입력 — 드래그로는 안 바뀜
        self.bpm_edit.setFixedWidth(70)
        self.bpm_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.bpm_edit.setStyleSheet(
            f"QLineEdit{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_PRIMARY};"
            f"border:1px solid {T.BORDER_DEFAULT};border-radius:8px;"
            f"padding:4px 8px;font-family:'{T.FONT_MONO}';font-size:12px;"
            "font-weight:700;}")
        self.bpm_edit.editingFinished.connect(self._on_bpm_edited)
        ctrl.addSpacing(8)
        ctrl.addWidget(self.bpm_edit)
        bpm_tag = QLabel("BPM")
        bpm_tag.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        ctrl.addWidget(bpm_tag)
        self.anchor_lbl = QLabel("")
        self.anchor_lbl.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_MONO}';"
            "font-size:13px;font-weight:700;")
        ctrl.addSpacing(10)
        ctrl.addWidget(self.anchor_lbl)
        ctrl.addStretch(1)
        self.confirm_btn = QPushButton("확정")
        self.confirm_btn.setStyleSheet(
            f"QPushButton{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_PRIMARY};"
            f"border:1px solid {T.BORDER_ACTIVE};border-radius:8px;"
            "padding:6px 18px;font-size:13px;font-weight:700;}"
            f"QPushButton:hover{{border:1px solid {T.WHITE};}}")
        self.confirm_btn.clicked.connect(self._on_confirm)
        ctrl.addWidget(self.confirm_btn)
        edit_col.addSpacing(4)
        edit_col.addLayout(ctrl)
        root.addLayout(edit_col)
        root.addStretch(1)

        # ── 조정 완료 → 다음 화면 — 좌측 패널 하단 고정 ──
        done_row = QHBoxLayout()
        done_row.addStretch(1)
        self.done_btn = QPushButton("조정 완료 → 코드·스케일 ▶")
        self.done_btn.setStyleSheet(T.qss_primary_btn())
        self.done_btn.clicked.connect(self._on_done)
        done_row.addWidget(self.done_btn)
        done_row.addStretch(1)
        root.addLayout(done_row)

        left_wrap = QWidget()
        left_wrap.setFixedWidth(420)
        left_wrap.setLayout(root)
        outer.addWidget(left_wrap)

        # ── 우측 디테일: 루프 리스트 + 마디별 코드표(스크롤) ──
        right = QVBoxLayout()
        right.setSpacing(10)
        loop_row = QHBoxLayout()
        grid_lbl = QLabel("마디별 코드 (클릭=코드 수정 · 드래그=루프 지정)")
        grid_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        loop_row.addWidget(grid_lbl)
        self.loops_row = QHBoxLayout()
        self.loops_row.setSpacing(6)
        loop_row.addSpacing(12)
        loop_row.addLayout(self.loops_row)
        loop_row.addStretch(1)
        self._loop_wrap = QWidget()
        self._loop_wrap.setLayout(loop_row)
        right.addWidget(self._loop_wrap)

        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setStyleSheet(
            "QScrollArea{border:none;background:transparent;}"
            "QScrollArea > QWidget > QWidget{background:transparent;}")
        self.holder = QWidget()
        self.holder.setStyleSheet("background:transparent;")
        hwrap = QHBoxLayout(self.holder)      # 표 전체 가운데 정렬
        hwrap.setContentsMargins(0, 0, 0, 0)
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
        outer.addLayout(right, 1)

    def showEvent(self, e):
        super().showEvent(e)
        # 잠금(불투명) 효과가 걸린 쪽은 페이드인 생략(효과 보존)
        zooms = [] if self._locked else [self.zoom_l, self.zoom_r]
        grids = [self.holder] if self._locked else []
        stagger([self.hint_lbl] + zooms + grids + [self.done_btn])

    # ── 격자 상태 ────────────────────────────────────────────────
    def _beats(self) -> int:
        return int((self.sig_box.currentData() or "4/4").split("/")[0])

    @property
    def bar_len(self) -> float:
        return self._beats() * self.beat_len

    def _refresh(self):
        for z in (self.zoom_l, self.zoom_r):
            z.set_grid(self.anchor, self.bar_len, self._beats())
        self.anchor_lbl.setText(f"시작 {self.anchor:.2f}s")

    # ── 로드 ─────────────────────────────────────────────────────
    def set_timeline(self, tl, model=None):
        if self.playhead:
            self.playhead.pause()
        self.tl = tl
        self._model = model
        self.anchor = tl.bar_times[0] if tl.bar_times else 0.0
        self.beat_len = tl.beat_sec()
        self._dur = (tl.bar_times[-1] if tl.bar_times else tl.total_sec()) or ZOOM_SEC
        idx = self.sig_box.findData(tl.time_sig)
        self.sig_box.blockSignals(True)
        self.sig_box.setCurrentIndex(idx if idx >= 0 else 1)
        self.sig_box.blockSignals(False)
        self.zoom_l.set_window(0.0, min(ZOOM_SEC, self._dur))
        self.zoom_r.set_window(max(0.0, self._dur - ZOOM_SEC), self._dur)
        wav = getattr(tl, "wav_ref", "")
        self.zoom_l.set_wave(_wave_peaks(wav, 0.0, min(ZOOM_SEC, self._dur)))
        self.zoom_r.set_wave(_wave_peaks(wav, max(0.0, self._dur - ZOOM_SEC), self._dur))
        self.bpm_edit.setText(f"{tl.bpm:.1f}")
        self.playhead = Playhead(self._dur, tl.audio_ref, self)
        self.playhead.positionChanged.connect(self._on_tick)
        self._applied = self._grid_state()   # 현재 격자 = 적용된 상태(무변경 시 재격자화 생략)
        self._set_locked(False)
        self._reset_drag()
        self._refresh()
        self._build_grid()
        self._build_loops()

    def pause(self):
        if self.playhead:
            self.playhead.pause()

    # ── 드래그 = 격자 평행이동(BPM 불변, 재격자화는 확정 시) ────
    def _on_drag(self, k: int, sec: float):
        """마디 k 선을 sec로 — 시작박이 그만큼 밀리거나 당겨진다(끝박도 동일)."""
        a = sec - k * self.bar_len
        if a < 0:
            a %= self.bar_len       # 시작박이 0초 앞으로 나가면 한 마디 안으로 되접기
        self.anchor = a
        self._refresh()

    def _on_drag_end(self, k: int):
        """드래그를 놓으면 그 마디선 위치부터 재생해 귀로 확인."""
        if self.playhead:
            self.playhead.seek(self.anchor + k * self.bar_len)
            self.playhead.play()

    def _on_bpm_edited(self):
        """BPM(간격) 직접 입력 — 시작박은 유지."""
        try:
            bpm = float(self.bpm_edit.text())
        except ValueError:
            self.bpm_edit.setText(f"{60.0 / self.beat_len:.1f}")
            return
        bpm = max(20.0, min(400.0, bpm))
        self.beat_len = 60.0 / bpm
        self.bpm_edit.setText(f"{bpm:.1f}")
        self._refresh()

    # ── 재생 ─────────────────────────────────────────────────────
    def _on_tick(self, sec: float):
        self.zoom_l.set_position(sec)
        self.zoom_r.set_position(sec)

    # ── 확정(멈춤+재격자화, 화면 유지) / 조정 완료(다음 화면) ────
    def _grid_state(self):
        return (self.sig_box.currentData(),
                round(60.0 / self.beat_len, 1), round(self.anchor, 4))

    def _apply(self):
        """격자 적용 — 재생 멈추고 재격자화(아래 코드 목록 갱신).

        같은 격자면 재적용하지 않는다(코드 수동 수정 보존).
        원자료 없는 구 캐시는 격자만 유지한 채 통과.
        """
        self.pause()
        if self.tl is None:
            return
        state = self._grid_state()
        if state == self._applied:
            return
        self.tl.time_sig = state[0] or self.tl.time_sig
        self.tl.bpm = state[1]
        if regrid_timeline(self.tl, self._model, anchor_sec=self.anchor):
            self._build_grid()
        self._applied = state

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
        for w in (self.zoom_l, self.zoom_r, self.sig_box, self.bpm_edit,
                  self.anchor_lbl):
            self._dim(w, locked)
        for w in (self._loop_wrap, self.holder):   # 미확정 격자의 코드표는 잠금
            self._dim(w, not locked)
        self.confirm_btn.setText("수정" if locked else "확정")
        if not locked:
            self._reset_drag()       # 박자 재편집 → 루프 드래그 중단

    def _on_confirm(self):
        if self._locked:                # 수정 — 잠금 해제(재확정 전까지 편집 가능)
            self._set_locked(False)
        else:                           # 확정 — 노래 멈춤 + 격자 적용 + 잠금
            self._apply()
            self._set_locked(True)

    def _on_done(self):
        if not self._locked:
            self._apply()      # 미확정 조정이 있으면 반영하고 진행
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
        for bar in range(total):
            seg = self.tl.segment_for_bar(bar)
            cell = self._make_cell(bar, seg, seg is not prev_seg)
            last_row = bar // BARS_PER_ROW
            self.grid.addWidget(cell, last_row, bar % BARS_PER_ROW)
            prev_seg = seg
        self.grid.setRowStretch(last_row + 1, 1)

    def _make_cell(self, bar: int, seg, is_new_chord: bool) -> QWidget:
        detour = bool(seg and seg.is_detour)   # 비다이아토닉(§3) — 빨강으로만 표시
        chord_txt = seg.chord.name if (seg and is_new_chord) else "／"
        # 종류만(근음 생략). 반복 마디(／)엔 스케일도 생략
        scale_txt = seg.scale.kind if (seg and seg.scale and is_new_chord) else ""

        cell = QFrame()
        if detour:                              # 비다이아토닉 → 빨강 강조
            border, bg = T.BADGE_OUT, T.BG_SURFACE
        else:
            border, bg = T.BORDER_DEFAULT, T.BG_INSET
        cell._base_qss = (
            f"QFrame{{background:{bg};border:2px solid {border};border-radius:8px;}}")
        cell._hl_qss = (                        # 루프 지정 선택/범위 하이라이트
            f"QFrame{{background:{T.BG_SURFACE_ALT};"
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

    def _edit_chord(self, seg):
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
                    lambda _, n=nm, sg=seg:
                        n != sg.chord.name and self._apply_chord(sg, n))
            if root_dia:                           # 스케일 안 루트도 굵게
                f = sub.menuAction().font(); f.setBold(True)
                sub.menuAction().setFont(f)
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(QCursor.pos())

    def _apply_chord(self, seg, name: str):
        """수동 선택 코드로 구간의 코드·스케일·리프를 재계산."""
        chord = parse_chord(name)
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
        bake_segment(self.tl, seg, self._model)   # 새 종류 리프 생성 + example 갱신
        self._build_grid()

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
        if self._drag_start is None or bar is None:
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
            self._edit_chord(seg)

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
            self._build_loops()

    def _build_loops(self):
        while self.loops_row.count():
            it = self.loops_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, lp in enumerate(self.tl.loops if self.tl else []):
            chip = QPushButton(
                f"{lp['name']}  {lp['start_bar'] + 1}–{lp['end_bar'] + 1}마디  ✕")
            chip.setToolTip("클릭하면 삭제")
            chip.setStyleSheet(T.qss_ghost_btn())
            chip.clicked.connect(lambda _, k=i: self._del_loop(k))
            self.loops_row.addWidget(chip)

    def _del_loop(self, i: int):
        if self.tl and 0 <= i < len(self.tl.loops):
            del self.tl.loops[i]
            self._build_loops()
