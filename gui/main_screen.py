"""[3] 메인 화면 = 플레이어 — ScaleRiff (디자인 스펙 §6.1, C안 코드 레인).

타임라인을 재생하며 위젯을 갱신만 한다(§4: 재분석 없음).
레이아웃: 상단바(뒤로/곡명/BPM/시간) · 코드 레인(고정 플레이헤드로 블록이 흐름)
        · 리프 뷰(연습 시) · 피아노 · 하단 컨트롤 한 줄(도전모드·루프·
        카운트인·재생)
"""
from __future__ import annotations

import bisect

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QMenu
)
from PyQt6.QtCore import pyqtSignal

from player.timeline import Timeline
from player.playhead import Playhead
from player.note_synth import shared_player
from analyze.theory import degree_number
from ml.model import load_model
from ml.generate import bake_examples

from gui import theme as T
from gui.anim import stagger
from gui.widgets.piano import PianoWidget
from gui.widgets.chord_lane import ChordLane
from gui.widgets.scrub_bar import ScrubBar
from gui.widgets.riff_view import RiffView

# 코드/가이드를 재생 위치보다 앞당겨 표시하는 보정값(초). 0 = 보정 없음.
SYNC_LOOKAHEAD_SEC = 0.0


def _fmt_sec(sec: float) -> str:
    s = max(0, int(sec))
    return f"{s // 60:02d}:{s % 60:02d}"


class MainScreen(QWidget):
    backToScoreRequested = pyqtSignal()
    backToLinkRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl: Timeline | None = None
        self.playhead: Playhead | None = None
        self.note_player = shared_player()
        self._last_idx = -1
        self._mode = "guide"               # guide ↔ practice(리프연습)
        self._difficulty = 0
        self._challenge_active = False
        self._selected_mode = "free"
        self._ml_model = load_model()      # 부트스트랩/학습 모델(없으면 규칙 폴백)
        # 재생 헤드에 동기화된 리프 이벤트(절대초, midi) — 일시정지/시킹과 함께 동작(§2)
        self._riff_events: list[tuple[float, int]] = []
        self._riff_times: list[float] = []
        self._riff_idx = 0

        self.content = T.compact_content(self)
        # 좌우 폭은 유지하고, 메인 화면은 창 하단까지 사용한다.
        self.layout().setStretch(1, 7)
        self.layout().setStretch(2, 0)
        root = QVBoxLayout(self.content)
        root.setContentsMargins(T.PAD_H, T.PAD_V, T.PAD_H, T.PAD_V)
        root.setSpacing(10)

        # ── 상단 바 ──
        top = QHBoxLayout()
        self.link_btn = QPushButton("← 링크")
        self.score_btn = QPushButton("← 악보")
        for b in (self.link_btn, self.score_btn):
            b.setStyleSheet(T.qss_ghost_btn())
        self.link_btn.clicked.connect(self.backToLinkRequested.emit)
        self.score_btn.clicked.connect(self.backToScoreRequested.emit)
        top.addWidget(self.link_btn)
        top.addWidget(self.score_btn)
        top.addSpacing(10)
        self.song_lbl = QLabel("—")
        self.song_lbl.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS}';"
            "font-size:15px;font-weight:700;")
        top.addWidget(self.song_lbl)
        top.addStretch(1)
        self.time_lbl = QLabel("")
        self.time_lbl.setStyleSheet(
            f"color:{T.TEXT_BODY};font-family:'{T.FONT_MONO}';font-size:12px;")
        top.addWidget(self.time_lbl)
        top.addSpacing(12)
        self.bpm_lbl = QLabel("")
        self.bpm_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;")
        top.addWidget(self.bpm_lbl)
        root.addLayout(top)

        # ── 코드 레인 — HUD+다음 미리보기 통합(고정 플레이헤드) ──
        self.lane = ChordLane()
        self.lane.seekRequested.connect(self._on_seek)
        root.addWidget(self.lane)

        # ── 리프 뷰(연습 시만) — 레인 바로 아래 밴드 ──
        self.riff = RiffView()
        riff_policy = self.riff.sizePolicy()
        riff_policy.setRetainSizeWhenHidden(True)
        self.riff.setSizePolicy(riff_policy)
        self.riff.setVisible(False)
        root.addWidget(self.riff)
        root.addSpacing(16)

        # ── 피아노 (리프연습과 무관하게 가만히 — 가이드 그대로) ──
        self.piano = PianoWidget()
        self.piano.notePlayed.connect(self.on_midi_note)
        root.addWidget(self.piano, 1)

        # ── 곡 전체 재생바(스크럽) — 건반 아래, seek로 레인과 연동 ──
        self.scrub = ScrubBar()
        self.scrub.seekRequested.connect(self._on_seek)
        root.addWidget(self.scrub)

        # ── 하단 컨트롤 한 줄: 도전모드·루프 + 재생 ──
        rrow = QHBoxLayout()
        self.challenge_btn = QPushButton("자유연습")
        self.challenge_btn.setFixedHeight(40)
        self.challenge_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{T.TEXT_PRIMARY};"
            f"border:1px solid {T.BORDER_ACTIVE};border-radius:10px;"
            "padding:4px 18px;font-size:13px;font-weight:700;}")
        self.challenge_menu = QMenu(self.challenge_btn)
        self.challenge_menu.setStyleSheet(
            f"QMenu{{background:{T.BG_INSET};color:{T.TEXT_BODY};"
            f"border:1px solid {T.BORDER_DEFAULT};padding:6px;}}"
            "QMenu::item{padding:8px 24px;}"
            f"QMenu::item:selected{{background:{T.BORDER_DEFAULT};}}")
        self._mode_actions = {}
        for mode, text in (("free", "자유연습"), ("riff", "리프연습")):
            action = self.challenge_menu.addAction(text)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, m=mode: self._select_practice(m))
            self._mode_actions[mode] = action
        scale_menu = self.challenge_menu.addMenu("스케일도전")
        scale_menu.setStyleSheet(self.challenge_menu.styleSheet())
        self._mode_actions["scale_challenge"] = scale_menu.menuAction()
        scale_menu.menuAction().setCheckable(True)
        self._difficulty_actions = []
        for level, text in enumerate([
                "Lv1 · 근음+코드톤", "Lv2 · 근음+스케일", "Lv3 · 코드톤+스케일"], 1):
            action = scale_menu.addAction(text)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, lv=level:
                                     self._select_practice("scale_challenge", lv))
            self._difficulty_actions.append(action)
        action = self.challenge_menu.addAction("리프도전")
        action.setCheckable(True)
        action.triggered.connect(lambda: self._select_practice("riff_challenge"))
        self._mode_actions["riff_challenge"] = action
        self._mode_actions["free"].setChecked(True)
        self.challenge_btn.setMenu(self.challenge_menu)
        rrow.addWidget(self.challenge_btn)
        # 루프 버튼 — 사이드바 토글(생성한 루프 리스트, 루프별 ON/OFF)
        self.loop_btn = QPushButton("루프 ▸")
        self.loop_btn.setCheckable(True)
        self.loop_btn.setFixedHeight(40)
        self.loop_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{T.TEXT_PRIMARY};"
            f"border:1px solid {T.BORDER_ACTIVE};border-radius:10px;"
            "padding:4px 18px;font-size:13px;font-weight:700;}"
            f"QPushButton:checked{{background:{T.WHITE};color:{T.BG_BASE};}}")
        self.loop_btn.clicked.connect(self._toggle_loop_panel)
        rrow.addWidget(self.loop_btn)
        rrow.addStretch(1)
        # 재생/일시정지 (흰 원형, §6.1)
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(60, 60)
        self.play_btn.setStyleSheet(
            f"QPushButton{{background:{T.WHITE};color:{T.BG_BASE};border:none;"
            f"border-radius:30px;font-size:22px;font-weight:700;}}"
            f"QPushButton:hover{{background:{T.TEXT_BODY};}}")
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
        pv.addLayout(self.loop_rows)
        pv.addStretch(1)

    def showEvent(self, e):
        super().showEvent(e)
        stagger([self.lane, self.piano, self.play_btn])

    # ── 루프 사이드바(§6): 루프별 ON/OFF ─────────────────────────
    def _toggle_loop_panel(self):
        if self.loop_btn.isChecked():
            self._build_loop_rows()
            self._place_loop_panel()
            self.loop_panel.show()
            self.loop_panel.raise_()
        else:
            self.loop_panel.hide()

    def _place_loop_panel(self):
        w = 270
        self.loop_panel.setGeometry(self.content.width() - w - 20, 64,
                                    w, min(380, self.content.height() - 130))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.loop_panel.isVisible():
            self._place_loop_panel()

    def _build_loop_rows(self):
        while self.loop_rows.count():
            it = self.loop_rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        loops = getattr(self.tl, "loops", []) if self.tl else []
        if not loops:
            lbl = QLabel("박자 조정 화면의 코드표에서\n루프를 만들 수 있어요.")
            lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;border:none;")
            self.loop_rows.addWidget(lbl)
            return
        for lp in loops:
            row = QWidget()
            row.setStyleSheet("border:none;")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            name = QLabel(f"{lp['name']}  {lp['start_bar'] + 1}–{lp['end_bar'] + 1}마디")
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
        if self._challenge_active:
            return []
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
            s, e = lp["start_bar"], lp["end_bar"] + 1
            if 0 <= s < e <= n:
                out.append((bars[s], bars[e]))
        return out

    # ── 난이도(§7.5) ─────────────────────────────────────────────
    def _apply_targets(self):
        """현재 구간의 존별 목표음을 건반 배지 필터로 반영(비목표음 흐리게)."""
        seg = self._current_segment()
        level = self._difficulty
        if self._mode == "practice" or seg is None or level == 0:
            self.piano.set_targets(0)
            return
        left = {seg.chord.root % 12} if level in (1, 2) else set(seg.chord_tones())
        right = set(seg.chord_tones()) if level == 1 else set(seg.note_set)
        self.piano.set_targets(self.tl.split_point, left, right)

    # ── ML 예시 재생 ─────────────────────────────────────────────
    def _current_segment(self):
        if not self.tl or self.playhead is None:
            return None
        return self.tl.segment_at(self.playhead.position_sec())

    # ── 리프를 재생에 함께 굽기(재생 헤드 동기) ──────────────────
    def _build_riff_events(self):
        """모든 구간의 리프 음을 (절대초, midi)로 펼쳐 정렬. 곡 타임라인에 '구워' 둔다.

        재생 헤드 위치에 맞춰 트리거하므로 일시정지·시킹 시 함께 멈추고 따라간다(§2).
        """
        ev: list[tuple[float, int]] = []
        if self.tl:
            beat = self.tl.beat_sec()
            for seg in self.tl.segments:
                for n in seg.example:
                    ev.append((seg.start_sec + n["beat_pos"] * beat, n["midi"]))
            ev.sort(key=lambda e: e[0])
        self._riff_events = ev
        self._riff_times = [t for t, _ in ev]

    def _seek_riff_idx(self, sec: float):
        """리프 재생 커서를 sec 위치로 이동(시킹/모드 진입 시 과거 음 몰아 재생 방지)."""
        self._riff_idx = bisect.bisect_left(self._riff_times, sec)

    # ── 타임라인 로드 ────────────────────────────────────────────
    def set_timeline(self, tl: Timeline):
        if self.playhead:
            self.playhead.pause()
        self._select_practice("free")
        self.tl = tl
        self._last_idx = -1
        self._build_loop_rows()            # 사용자 루프 리스트(사이드바) 갱신
        if not getattr(tl, "scale_riffs", None):   # 아직이면 1회 굽기(§8)
            bake_examples(tl, self._ml_model)
        self._build_riff_events()          # 리프를 곡에 함께 구움(§2)
        self._riff_idx = 0
        self.playhead = Playhead(tl.content_end(), tl.audio_ref, self)
        self.playhead.positionChanged.connect(self._on_tick)
        self.playhead.stateChanged.connect(self._on_state)

        self.song_lbl.setText(tl.title or tl.audio_ref or "내 곡")
        self.bpm_lbl.setText(f"{tl.key}  ·  {tl.bpm:.0f} BPM")
        self.lane.set_timeline(tl)
        self.scrub.set_timeline(tl)
        self.scrub.set_position(0.0)
        self.time_lbl.setText(f"{_fmt_sec(0)} / {_fmt_sec(tl.total_sec())}")
        self._render_at(0.0)

    def pause(self):
        if self.playhead:
            self.playhead.pause()

    # ── 연습 / 도전 모드 선택 ───────────────────────────────────
    def _select_practice(self, mode: str, level: int = 0):
        challenge = mode in ("scale_challenge", "riff_challenge")
        if challenge or self._challenge_active:
            self.pause()
        self._selected_mode = mode
        self._challenge_active = challenge
        self._mode = "practice" if mode in ("riff", "riff_challenge") else "guide"
        self._difficulty = level
        practice = (self._mode == "practice")
        for lv, action in enumerate(self._difficulty_actions, 1):
            action.setChecked(mode == "scale_challenge" and lv == level)
        for key, action in self._mode_actions.items():
            action.setChecked(key == mode)
        self.challenge_btn.setText(self._mode_actions[mode].text())
        self.challenge_btn.setToolTip(
            self._difficulty_actions[level - 1].text() if mode == "scale_challenge" else "")
        self.lane.setEnabled(not challenge)
        self.scrub.setEnabled(not challenge)
        self.loop_btn.setVisible(not challenge)
        if challenge:
            self.loop_btn.setChecked(False)
            self.loop_panel.hide()
        self.riff.setVisible(practice)
        self._apply_targets()
        if practice:
            seg = self._current_segment()
            if seg and self.tl:
                self.riff.set_segment(seg, self.tl.bpm, self.tl.time_sig_beats())
            # 현재 위치부터 리프 재생(과거 음은 건너뜀)
            self._build_riff_events()
            self._seek_riff_idx(self.playhead.position_sec() if self.playhead else 0.0)
        else:
            self.riff.clear()
        if challenge:
            self._reset_challenge()
        else:
            self._on_state(self.playhead.is_playing() if self.playhead else False)

    def _reset_challenge(self):
        self.pause()
        self._last_idx = -1
        self._seek_to(0.0)
        self._on_state(False)

    # ── 재생 제어 ────────────────────────────────────────────────
    def _toggle_play(self):
        if self.playhead:
            if self._challenge_active:
                if self.playhead.is_playing():
                    self._reset_challenge()
                else:
                    self._seek_to(0.0)
                    self.playhead.play()
            else:
                self.playhead.toggle()

    def _on_state(self, playing: bool):
        self.challenge_btn.setEnabled(not (self._challenge_active and playing))
        if self._challenge_active:
            self.play_btn.setText("포기" if playing else "도전")
        else:
            self.play_btn.setText("⏸" if playing else "▶")

    def _on_seek(self, sec: float):
        if self._challenge_active:
            return
        self._seek_to(sec)

    def _seek_to(self, sec: float):
        if self.playhead:
            self.playhead.seek(sec)
            self._render_at(sec)
            self._seek_riff_idx(sec)        # 리프 커서도 함께 점프

    def _on_tick(self, sec: float):
        self.lane.set_position(sec)
        self.scrub.set_position(sec)       # 레인·재생바 함께 이동
        if self.tl:
            self.time_lbl.setText(
                f"{_fmt_sec(sec)} / {_fmt_sec(self.tl.total_sec())}")
        # 사용자 루프(§6): 켜진 루프 끝에 닿으면 시작으로
        if self.playhead and self.playhead.is_playing():
            for s0, e0 in self._loop_spans():
                if e0 <= sec < e0 + 0.5:
                    self._seek_to(s0)
                    return
        self._render_at(sec + SYNC_LOOKAHEAD_SEC)   # 구간 변경 시 무거운 갱신
        self._update_live(sec)                       # 매 틱 카운트인·리프 헤드
        # 리프를 재생 헤드에 맞춰 트리거(재생 중일 때만 → 일시정지 시 함께 멈춤, §2)
        if self._mode == "practice" and self.playhead and self.playhead.is_playing():
            ev = self._riff_events
            while self._riff_idx < len(ev) and ev[self._riff_idx][0] <= sec:
                self.note_player.play_note(ev[self._riff_idx][1])
                self._riff_idx += 1

    # ── 상태 → UI 렌더 (구간 변경 시) ────────────────────────────
    def _render_at(self, sec: float):
        if not self.tl or not self.tl.segments:
            return
        idx = self.tl.segment_index_at(sec)
        self._update_scale_preview(sec, idx)
        if idx < 0 or idx == self._last_idx:
            return
        self._last_idx = idx
        seg = self.tl.segments[idx]
        self.piano.set_scale(seg.note_set, seg.chord_tones())
        self.piano.set_degrees(
            {pc: degree_number(pc, seg.scale_root) for pc in seg.note_set})
        self.piano.set_pressed(set())
        self._apply_targets()              # 난이도 목표음 필터(구간별, §7.5)
        # 현재/다음 코드·스케일은 코드 레인이 스스로 그림(set_position)
        # 리프연습: 새 구간 진입 시 리프 뷰만 갱신(재생은 _on_tick이 헤드 동기로 트리거)
        if self._mode == "practice":
            self.riff.set_segment(seg, self.tl.bpm, self.tl.time_sig_beats())

    def _update_scale_preview(self, sec: float, idx: int):
        self.piano.set_preview()
        if idx < 0:
            return
        seg = self.tl.segments[idx]
        upcoming = self.tl.next_segment(seg)
        boundary = upcoming.start_sec if upcoming else seg.end_sec
        for start, end in self._loop_spans():
            if start <= sec < end and end <= boundary:
                boundary = end
                upcoming = self.tl.segment_at(start)
                break
        if upcoming is None or boundary > self.tl.content_end():
            return
        if (seg.scale_name, seg.chord_tones(), set(seg.note_set)) == (
                upcoming.scale_name, upcoming.chord_tones(), set(upcoming.note_set)):
            return
        lead = min(4 * self.tl.beat_sec(), boundary - seg.start_sec)
        if lead <= 0 or not boundary - lead <= sec < boundary:
            return
        self.piano.set_preview(upcoming.note_set, upcoming.chord_tones(),
                               upcoming.scale_root, (sec - boundary + lead) / lead)

    # ── 매 틱 라이브 갱신: 리프 헤드 ─────────────────────────────
    def _update_live(self, sec: float):
        if not self.tl or not self.tl.segments:
            return
        idx = self.tl.segment_index_at(sec)
        if idx < 0:
            return
        seg = self.tl.segments[idx]
        if self._mode == "practice" and self.playhead and self.playhead.is_playing():
            self.riff.set_play_pos_sec(sec, seg.start_sec, self.tl.bpm)

    # ── 입력 콜백 ────────────────────────────────────────────────
    def on_midi_note(self, midi: int, is_on: bool):
        if not self.tl or self.playhead is None:
            return
        pressed = set(self.piano._pressed)
        if is_on:
            pressed.add(midi)
            self.note_player.play_note(midi)
        else:
            pressed.discard(midi)
        self.piano.set_pressed(pressed)
