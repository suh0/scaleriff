"""[3] 메인 화면 = 플레이어 — ScaleRiff (디자인 스펙 §6.1, C안 코드 레인).

타임라인을 재생하며 위젯을 갱신만 한다(§4: 재분석 없음).
레이아웃: 상단바(뒤로/곡명/BPM/시간) · 코드 레인(고정 플레이헤드로 블록이 흐름)
        · 리프 뷰(연습 시) · 피아노 · 하단 컨트롤 한 줄(루프·리프학습·재생)
"""
from __future__ import annotations

import bisect

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QComboBox, QDialog, QFormLayout, QSlider, QCheckBox, QScrollArea, QMessageBox
)
from PyQt6.QtCore import pyqtSignal, Qt, QEvent

from player.timeline import Timeline
from player.playhead import Playhead
from player.note_synth import shared_player
from analyze.theory import degree_number
from ml.model import load_model
from ml.generate import _landing_pc

from gui import theme as T
from gui.anim import fade_in, reduced_motion, set_reduced_motion
from gui.widgets.elided_label import ElidedLabel
from gui.widgets.piano import MIDI_HIGH, MIDI_LOW, PianoWidget
from gui.widgets.scrub_bar import ScrubBar
from gui.widgets.falling_notes import FallingNotes
from gui.riff_dialog import RiffDialog

# 코드/가이드를 재생 위치보다 앞당겨 표시하는 보정값(초). 0 = 보정 없음.
SYNC_LOOKAHEAD_SEC = 0.0


def _fmt_sec(sec: float) -> str:
    s = max(0, int(sec))
    return f"{s // 60:02d}:{s % 60:02d}"


class MainScreen(QWidget):
    backToSetupRequested = pyqtSignal()
    backToLinkRequested = pyqtSignal()
    midiPortRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl: Timeline | None = None
        self.playhead: Playhead | None = None
        self.note_player = shared_player()
        self._last_idx = -1
        self._mode = "guide"               # guide ↔ practice(리프연습)
        self._ml_model = load_model()      # 부트스트랩/학습 모델(없으면 규칙 폴백)
        # 재생 헤드에 동기화된 리프 이벤트(절대초, midi) — 일시정지/시킹과 함께 동작(§2)
        self._riff_events: list[tuple[float, int]] = []
        self._riff_times: list[float] = []
        self._riff_idx = 0
        self._riff_durations = []
        self._held_keys = set()
        self._riff_volume = .8
        self._input_volume = .8
        self._audio_volume = .8
        self._midi_ports = []
        self._midi_name = ""
        self._last_tick = 0.0
        self._seeking = False
        self._monitor_seg = None          # 모니터박스에 표시 중인 현재 구간
        self._monitor_prev = ""          # push 동안 밀려나는 이전 코드명

        self.content = T.compact_content(self)
        root = QVBoxLayout(self.content)
        root.setContentsMargins(T.PAD_H, 16, T.PAD_H, 16)
        root.setSpacing(6)

        # ── 상단 바 ──
        top = QHBoxLayout()
        self.link_btn = QPushButton("← 링크")
        self.score_btn = QPushButton("← 학습 설정")
        for b in (self.link_btn, self.score_btn):
            b.setStyleSheet(T.qss_ghost_btn())
        self.link_btn.clicked.connect(self.backToLinkRequested.emit)
        self.score_btn.clicked.connect(self.backToSetupRequested.emit)
        top.addWidget(self.link_btn)
        top.addWidget(self.score_btn)
        top.addSpacing(10)
        self.song_lbl = ElidedLabel("—")
        self.song_lbl.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS}';"
            "font-size:15px;font-weight:700;")
        top.addWidget(self.song_lbl, 1)
        top.addSpacing(12)
        self.bpm_lbl = QLabel("")
        self.bpm_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;")
        top.addWidget(self.bpm_lbl)
        top.addSpacing(12)
        self.settings_btn = QPushButton("입력·소리")
        self.settings_btn.setStyleSheet(T.qss_ghost_btn())
        top.addWidget(self.settings_btn)
        root.addLayout(top)
        self.settings_btn.clicked.connect(self._show_settings)

        # ── 모니터박스 자리(guide_space~건반) — 현재/다음 코드 + 리프 낙하 ──
        self.guide_space = QWidget()
        self.guide_space.setMinimumHeight(40)
        root.addWidget(self.guide_space, 1)

        # ── 피아노 (리프연습과 무관하게 가만히 — 가이드 그대로) ──
        self.piano = PianoWidget()
        self.piano.notePlayed.connect(self.on_midi_note)
        root.addWidget(self.piano, 2)
        self.riff = FallingNotes(self.piano, self.content)
        self.piano.installEventFilter(self)

        # ── 곡 전체 재생바(스크럽) — 건반 아래, seek로 레인과 연동 ──
        self.scrub = ScrubBar()
        self.scrub.seekRequested.connect(self._on_seek)
        scrub_row = QHBoxLayout()
        self.time_lbl = QLabel("00:00")
        self.total_time_lbl = QLabel("00:00")
        for label in (self.time_lbl, self.total_time_lbl):
            label.setStyleSheet(
                f"color:{T.TEXT_BODY};font-family:'{T.FONT_MONO}';font-size:12px;")
        scrub_row.addWidget(self.time_lbl)
        scrub_row.addWidget(self.scrub, 1)
        scrub_row.addWidget(self.total_time_lbl)
        root.addLayout(scrub_row)

        # ── 하단 컨트롤 한 줄: 루프·리프학습 + 재생 ──
        rrow = QHBoxLayout()
        # 루프 버튼 — 사이드바 토글(생성한 루프 리스트, 루프별 ON/OFF)
        self.loop_btn = QPushButton("루프")
        self.loop_btn.setCheckable(True)
        self.loop_btn.setFixedHeight(36)
        self.loop_btn.setStyleSheet(T.qss_ghost_btn())
        self.loop_btn.clicked.connect(self._toggle_loop_panel)
        rrow.addWidget(self.loop_btn)
        self.riff_btn = QPushButton("리프모드")
        self.riff_btn.setFixedHeight(36)
        self.riff_btn.setStyleSheet(T.qss_ghost_btn())
        self.riff_btn.clicked.connect(self._toggle_riff_mode)
        rrow.addWidget(self.riff_btn)
        rrow.addStretch(1)
        # 재생/일시정지 (흰 원형, §6.1)
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(52, 52)
        self.play_btn.setAccessibleName("재생 또는 일시정지")
        self.play_btn.setToolTip("재생 / 일시정지")
        self.play_btn.setStyleSheet(
            f"QPushButton{{background:{T.WHITE};color:{T.BG_BASE};border:1px solid transparent;"
            "min-width:50px;max-width:50px;min-height:50px;max-height:50px;"
            "border-radius:26px;font-size:20px;font-weight:700;padding:0;}"
            f"QPushButton:hover{{background:{T.TEXT_BODY};}}"
            f"QPushButton:pressed{{background:{T.BORDER_ACTIVE};}}"
            f"QPushButton:focus{{border-color:{T.BORDER_ACTIVE};}}")
        self.play_btn.clicked.connect(self._toggle_play)
        playback_row = QGridLayout()
        playback_row.addLayout(rrow, 0, 0)
        playback_row.addWidget(self.play_btn, 0, 1)
        playback_row.addWidget(QWidget(), 0, 2)
        for column in (0, 2):
            playback_row.setColumnStretch(column, 1)
            playback_row.setColumnMinimumWidth(column, rrow.minimumSize().width())
        root.addLayout(playback_row)

        # ── 루프 사이드바 (오버레이) — 생성한 루프 리스트 + 루프별 ON/OFF ──
        self.loop_panel = QFrame(self.content)
        self.loop_panel.hide()
        self.loop_panel.setStyleSheet(
            f"QFrame{{background:{T.BG_SURFACE};border:1px solid {T.BORDER_DEFAULT};"
            "border-radius:12px;}")
        pv = QVBoxLayout(self.loop_panel)
        pv.setContentsMargins(16, 14, 16, 14)
        pv.setSpacing(6)
        panel_title = QLabel("루프")
        panel_title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-size:14px;font-weight:700;border:none;")
        pv.addWidget(panel_title)
        self.loop_rows = QVBoxLayout()
        self.loop_rows.setSpacing(4)
        self.loop_rows.setAlignment(Qt.AlignmentFlag.AlignTop)
        loop_host = QWidget()
        loop_host.setObjectName("loopList")
        loop_host.setStyleSheet(f"QWidget#loopList{{background:{T.BG_SURFACE};}}")
        loop_host.setLayout(self.loop_rows)
        self.loop_scroll = QScrollArea()
        self.loop_scroll.setWidgetResizable(True)
        self.loop_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.loop_scroll.setWidget(loop_host)
        pv.addWidget(self.loop_scroll, 1)

    def showEvent(self, e):
        super().showEvent(e)
        # 연주 가이드와 건반은 즉시 표시한다.

    # ── 루프 사이드바(§6): 루프별 ON/OFF ─────────────────────────
    def _toggle_loop_panel(self):
        if self.loop_btn.isChecked():
            self._build_loop_rows()
            self._place_loop_panel()
            self.loop_panel.show()
            self.loop_panel.raise_()
            fade_in(self.loop_panel)
        else:
            self.loop_panel.hide()

    def _place_loop_panel(self):
        w = 310
        self.loop_panel.setGeometry(self.content.width() - w - 20, 64,
                                    w, min(380, self.content.height() - 130))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "riff"):
            self._place_falling_notes()
        if self.loop_panel.isVisible():
            self._place_loop_panel()

    def _place_falling_notes(self):
        geo = self.piano._geometry()
        if geo:
            top = self.guide_space.y()
            bottom = self.piano.y() + geo[2]
            self.riff.setGeometry(self.piano.x(), top, self.piano.width(), max(1, int(bottom - top)))

    def eventFilter(self, watched, event):
        if watched is self.piano and event.type() in (QEvent.Type.Move, QEvent.Type.Resize):
            self._place_falling_notes()
        return super().eventFilter(watched, event)

    def _build_loop_rows(self):
        while self.loop_rows.count():
            it = self.loop_rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        loops = getattr(self.tl, "loops", []) if self.tl else []
        if not loops:
            lbl = QLabel("코드 편집에서 여러 마디를 드래그해\n반복할 구간을 만들어보세요.")
            lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;border:none;")
            self.loop_rows.addWidget(lbl)
            return
        for lp in loops:
            row = QWidget()
            row.setStyleSheet("border:none;")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            name = ElidedLabel(f"{lp['name']}  {lp['start_bar'] + 1}–{lp['end_bar'] + 1}마디")
            name.setStyleSheet(f"color:{T.TEXT_BODY};font-size:12px;border:none;")
            h.addWidget(name, 1)
            btn = QPushButton("● ON" if lp.get("on") else "○ OFF")
            btn.setCheckable(True)
            btn.setChecked(bool(lp.get("on")))
            btn.setFixedWidth(66)
            btn.setStyleSheet(T.qss_ghost_btn())
            btn.toggled.connect(lambda on, l=lp, b=btn: self._toggle_loop(l, b, on))
            h.addWidget(btn)
            self.loop_rows.addWidget(row)

    @staticmethod
    def _toggle_loop(lp: dict, btn: QPushButton, on: bool):
        lp["on"] = on
        btn.setText("● ON" if on else "○ OFF")

    def _loop_spans(self) -> list[tuple[float, float]]:
        """켜진 사용자 루프의 (start_sec, end_sec) — 타임라인 마디 격자 기준."""
        loops = getattr(self.tl, "loops", []) if self.tl else []
        if not loops:
            return []
        bars = self.tl.bar_times
        if len(bars) < 2:
            # 구 캐시는 BPM으로 마디 격자를 복원한다.
            bar_len = self.tl.beat_sec() * self.tl.time_sig_beats()
            start, end = self.tl.content_span
            if end <= start:
                start, end = 0.0, self.tl.total_sec()
            if bar_len <= 0 or end <= start:
                return []
            bars = []
            t = start
            while t < end - 1e-6:
                bars.append(t)
                t += bar_len
            bars.append(end)
        n = len(bars) - 1
        out = []
        for lp in loops:
            if not lp.get("on"):
                continue
            if "start_sec" in lp and "end_sec" in lp:
                out.append((lp["start_sec"], lp["end_sec"]))
                continue
            s, e = lp["start_bar"], lp["end_bar"] + 1
            if 0 <= s < e <= n:
                out.append((bars[s], bars[e]))
        return out

    # ── 리프를 재생에 함께 굽기(재생 헤드 동기) ──────────────────
    def _build_riff_events(self):
        """모든 구간의 리프 음을 (절대초, midi)로 펼쳐 정렬. 곡 타임라인에 '구워' 둔다.

        재생 헤드 위치에 맞춰 트리거하므로 일시정지·시킹 시 함께 멈추고 따라간다(§2).
        """
        ev: list[tuple[float, int]] = []
        durations = {}
        falling = []
        if self.tl:
            beat = self.tl.beat_sec()
            for seg in self.tl.segments:
                for n in seg.example:
                    onset = self.tl.beat_at(seg.start_sec) + n["beat_pos"]
                    when = self.tl.time_at_beat(onset)
                    ev.append((when, n["midi"]))
                    durations[(when, n["midi"])] = self.tl.time_at_beat(onset + n.get("dur_beats", .5)) - when
                    pc = n["midi"] % 12
                    if pc in seg.chord_tones():
                        color = T.BADGE_ROOT if pc == seg.scale_root else T.BADGE_CHORD
                    else:
                        color = T.BADGE_SCALE
                    falling.append((ev[-1][0], n["midi"], color,
                                    self.tl.time_at_beat(onset + n.get("dur_beats", .5)) - when))
            ev.sort(key=lambda e: e[0])
        self._riff_events = ev
        self._riff_times = [t for t, _ in ev]
        self._riff_durations = [durations.get(item, .25) for item in ev]
        self.riff.set_events(falling, self.tl.beat_sec() if self.tl else 0.5,
                             self.tl.beat_grid() if self.tl else [])

    def _seek_riff_idx(self, sec: float):
        """리프 재생 커서를 sec 위치로 이동(시킹/모드 진입 시 과거 음 몰아 재생 방지)."""
        self._riff_idx = bisect.bisect_left(self._riff_times, sec)

    # ── 타임라인 로드 ────────────────────────────────────────────
    def set_timeline(self, tl: Timeline):
        if self.playhead:
            self.playhead.pause()
            self.playhead.deleteLater()
        self._select_practice("free")
        self.tl = tl
        self._last_idx = -1
        self._monitor_seg = None
        self._build_loop_rows()            # 사용자 루프 리스트(사이드바) 갱신
        self._build_riff_events()          # 리프를 곡에 함께 구움(§2)
        self._riff_idx = 0
        self.playhead = Playhead(tl.content_end(), tl.audio_ref, self)
        self.playhead.positionChanged.connect(self._on_tick)
        self.playhead.stateChanged.connect(self._on_state)
        self.playhead.errorOccurred.connect(lambda msg: QMessageBox.warning(self, "재생 오류", msg))
        self.playhead.set_volume(self._audio_volume)
        self._held_keys.clear()
        self._last_tick = 0.0

        self.song_lbl.setText(tl.title or tl.audio_ref or "내 곡")
        self.bpm_lbl.setText(f"{tl.key}  ·  {tl.bpm:.0f} BPM")
        self.scrub.set_timeline(tl)
        self.total_time_lbl.setText(_fmt_sec(tl.total_sec()))
        self._seek_to(tl.count_in_start())   # 처음 = 예비박부터(음수는 무음 프리롤)
        self.scrub.set_position(self.playhead.position_sec())
        self.time_lbl.setText(_fmt_sec(self.playhead.position_sec()))

    def pause(self):
        if self.playhead:
            self.playhead.pause()
        self.note_player.stop_all()
        self._held_keys.clear()
        self.piano.set_pressed(set())

    # ── 연습 모드 선택 ──────────────────────────────────────────
    def _select_practice(self, mode: str):
        self._mode = "practice" if mode == "riff" else "guide"
        practice = (self._mode == "practice")
        self.riff_btn.setText("리프모드 해제" if practice else "리프모드")
        self.riff.show_notes = practice
        self._place_falling_notes()
        self.riff.raise_()
        self.loop_panel.raise_()
        if practice:
            # 현재 위치부터 리프 재생(과거 음은 건너뜀)
            self._build_riff_events()
            self._seek_riff_idx(self.playhead.position_sec() if self.playhead else 0.0)
        self.riff.set_position(self.playhead.position_sec() if self.playhead else 0.0,
                               self._loop_spans())
        self._render_at(self.playhead.position_sec() if self.playhead else 0.0)
        self._on_state(self.playhead.is_playing() if self.playhead else False)

    # ── 리프모드: 학습 설정 조건으로 곡 전체 2마디 패턴 리프 생성 → 확정 시 리프연습 ──
    def _toggle_riff_mode(self):
        """켜기 = 리프 생성 창(확정 시 진입), 해제 = 자유연습 — 둘 다 곡 처음(예비박)으로."""
        if self._mode == "practice":
            self.pause()
            self._select_practice("free")
            self._seek_to(self.tl.count_in_start())
        else:
            self._open_riff_dialog()

    def _open_riff_dialog(self):
        if not self.tl:
            return
        self.pause()
        dialog = RiffDialog(self.tl, self._ml_model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._select_practice("riff")
            self._seek_to(self.tl.count_in_start())

    # ── 재생 제어 ────────────────────────────────────────────────
    def _toggle_play(self):
        if self.playhead:
            self.playhead.toggle()

    def _on_state(self, playing: bool):
        if not playing:
            self.note_player.stop_all()
            self._held_keys.clear()
            self.piano.set_pressed(set())
        self.play_btn.setText("⏸" if playing else "▶")
        action = "일시정지" if playing else "재생"
        self.play_btn.setAccessibleName(action)
        self.play_btn.setToolTip(action)

    def _on_seek(self, sec: float):
        self._seek_to(sec)

    def _seek_to(self, sec: float):
        if self.playhead:
            self.note_player.stop_all()
            self._held_keys.clear()
            self._seek_riff_idx(sec)
            self._seeking = True
            try:
                self.playhead.seek(sec)
            finally:
                self._seeking = False
            self._last_tick = sec
            self._render_at(sec)
            self._seek_riff_idx(sec)        # 리프 커서도 함께 점프

    def _on_tick(self, sec: float):
        self.scrub.set_position(sec)
        if self.tl:
            self.time_lbl.setText(_fmt_sec(sec))
        if self._seeking:
            self._render_at(sec)
            return
        # 사용자 루프(§6): 켜진 루프 끝에 닿으면 시작으로
        if self.playhead and self.playhead.is_playing():
            for s0, e0 in self._loop_spans():
                if self._last_tick < e0 <= sec:
                    self._seek_to(s0)
                    return
        self._last_tick = sec
        self._render_at(sec + SYNC_LOOKAHEAD_SEC)   # 구간 변경 시 무거운 갱신
        # 리프를 재생 헤드에 맞춰 트리거(재생 중일 때만 → 일시정지 시 함께 멈춤, §2)
        if self._mode == "practice" and self.playhead and self.playhead.is_playing():
            ev = self._riff_events
            while self._riff_idx < len(ev) and ev[self._riff_idx][0] <= sec:
                duration = self._riff_durations[self._riff_idx] if self._riff_idx < len(self._riff_durations) else .25
                self.note_player.play_note(ev[self._riff_idx][1], duration,
                                           round(100 * self._riff_volume))
                self._riff_idx += 1

    # ── 상태 → UI 렌더 (구간 변경 시) ────────────────────────────
    def _render_at(self, sec: float):
        if not self.tl or not self.tl.segments:
            return
        idx = self.tl.segment_index_at(sec)
        self._update_scale_preview(sec, idx)
        if idx < 0:
            self._last_idx = -1
            self.piano.set_scale([], [])
            self.piano.set_degrees({})
            return
        if idx == self._last_idx:
            return
        self._last_idx = idx
        seg = self.tl.segments[idx]
        chord_tones = seg.chord_tones()
        goal = self.tl.practice.get("goal")
        if self.tl.practice.get("method") == "landing" and goal != "chord_tone":
            target = _landing_pc(seg, goal)      # 착지 목표음만 초록으로 강조
            chord_tones = [target] if target is not None else chord_tones
        self.piano.set_scale(seg.note_set, chord_tones)
        self.piano.set_degrees({pc: degree_number(pc, seg.scale_root) for pc in seg.note_set})
        self.piano.set_pressed({m for _, m in self._held_keys})
        # 현재/다음 코드는 모니터박스가 그림(_update_monitor)

    def _update_scale_preview(self, sec: float, idx: int):
        self.piano.set_preview()
        self._place_falling_notes()
        spans = self._loop_spans()
        self.riff.set_position(sec, spans)
        seg = self.tl.segments[idx] if idx >= 0 else None
        if seg is None:      # 예비박: 첫 코드를 다음 코드로 예고
            first = self.tl.segments[0]
            upcoming = first if sec < first.start_sec else None
            boundary = first.start_sec
        else:
            upcoming = self.tl.next_segment(seg)
            boundary = upcoming.start_sec if upcoming else seg.end_sec
        change = seg.start_sec if seg else sec
        for start, end in spans:
            if start <= sec < end:
                change = max(change, start)
                if end <= boundary:
                    boundary = end
                    upcoming = self.tl.segment_at(start)
                break
        if upcoming is not None and boundary > self.tl.content_end():
            upcoming = None
        lead = min(4 * self.tl.beat_sec(), boundary - (seg.start_sec if seg else sec - 4 * self.tl.beat_sec()))
        grow = (sec - boundary + lead) / lead if upcoming and lead > 0 and boundary - lead <= sec < boundary else 0.0
        self._update_monitor(sec, seg, upcoming, grow, change)
        if self._mode == "practice" or seg is None or upcoming is None or grow <= 0:
            return
        if (seg.scale_name, seg.chord_tones(), set(seg.note_set)) == (
                upcoming.scale_name, upcoming.chord_tones(), set(upcoming.note_set)):
            return
        self.piano.set_preview(upcoming.note_set, upcoming.chord_tones(),
                               upcoming.scale_root, grow)

    def _update_monitor(self, sec, seg, upcoming, grow, change):
        """모니터박스 코드 표시 — 재생 중 코드가 바뀌면 이전 코드를 밀어내는 push(0.5박)."""
        if seg is not self._monitor_seg:
            playing = self.playhead is not None and self.playhead.is_playing()
            self._monitor_prev = self._monitor_seg.chord.name if playing and self._monitor_seg else ""
            self._monitor_seg = seg
        push = min(1.0, max(0.0, (sec - change) / (0.5 * self.tl.beat_sec()))) if self._monitor_prev else 1.0
        if push >= 1:
            self._monitor_prev = ""
        self.riff.set_chords(seg.chord.name if seg else "",
                             seg.scale.kind if seg and seg.scale else "",
                             upcoming.chord.name if upcoming else "",
                             self._monitor_prev, grow, push)

    # ── 입력 콜백 ────────────────────────────────────────────────
    def on_midi_note(self, midi: int, is_on: bool):
        self.on_midi_event({"type": "note", "pitch": midi, "is_on": is_on,
                            "velocity": 100, "channel": 0})

    def on_midi_event(self, event: dict):
        if not self.tl or self.playhead is None:
            return
        channel = event.get("channel", 0)
        if event.get("type") == "pedal":
            self.note_player.set_pedal(event.get("down", False), channel)
            return
        midi = event.get("pitch", event.get("midi"))
        if midi is None:
            return
        shown = MIDI_LOW <= midi <= MIDI_HIGH   # 두 옥타브 밖 음은 소리만 낸다
        if event.get("is_on", False):
            if shown:
                self._held_keys.add((channel, midi))
            self.note_player.note_on(midi, round(event.get("velocity", 100) * self._input_volume), channel)
        else:
            self._held_keys.discard((channel, midi))
            self.note_player.note_off(midi, channel)
        self.piano.set_pressed({m for _, m in self._held_keys})

    def set_midi_status(self, ports, name="", error=""):
        self._midi_ports, self._midi_name = list(ports), name
        self.settings_btn.setText("입력·소리 ●" if name else "입력·소리 ○")
        self.settings_btn.setToolTip(error or (f"MIDI: {name}" if name else "MIDI 미연결 · 화면 건반으로 연습 가능"))

    def _show_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("입력·소리")
        dialog.setStyleSheet(T.qss_app())
        dialog.setMinimumWidth(440)
        form = QFormLayout(dialog)
        form.setContentsMargins(24, 24, 24, 24)
        form.setVerticalSpacing(14)
        heading = QLabel("입력과 소리")
        heading.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-size:22px;font-weight:700;")
        form.addRow(heading)
        ports = QComboBox()
        ports.addItem("장치를 선택하세요", "")
        for name in self._midi_ports:
            ports.addItem(name, name)
        ports.setCurrentIndex(max(0, ports.findData(self._midi_name)))
        form.addRow("MIDI 장치", ports)
        reconnect = QPushButton("선택 장치 연결 / 새로 검색")
        def reconnect_ports():
            self.midiPortRequested.emit(ports.currentData() or "")
            ports.clear()
            ports.addItem("장치를 선택하세요", "")
            for name in self._midi_ports:
                ports.addItem(name, name)
            ports.setCurrentIndex(max(0, ports.findData(self._midi_name)))
        reconnect.clicked.connect(reconnect_ports)
        form.addRow(reconnect)
        for text, key in (("원곡 음량", "_audio_volume"), ("리프 음량", "_riff_volume"),
                          ("내 연주 모니터", "_input_volume")):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(round(getattr(self, key) * 100))
            slider.valueChanged.connect(lambda value, k=key: self._set_volume(k, value / 100))
            form.addRow(text, slider)
        motion = QCheckBox("화면 전환 효과 줄이기")
        motion.setChecked(reduced_motion())
        motion.setToolTip("페이드 전환을 생략합니다. 박자에 맞춘 낙하 가이드와 다음 음 예고는 유지됩니다.")
        motion.toggled.connect(set_reduced_motion)
        form.addRow("화면 효과", motion)
        close = QPushButton("닫기")
        close.setStyleSheet(T.qss_primary_btn())
        close.clicked.connect(dialog.accept)
        form.addRow(close)
        dialog.exec()

    def _set_volume(self, key, value):
        setattr(self, key, value)
        if key == "_audio_volume" and self.playhead:
            self.playhead.set_volume(value)
