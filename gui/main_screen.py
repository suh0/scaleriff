"""[3] 메인 화면 = 플레이어 — ScaleRiff (디자인 스펙 §6.1).

타임라인을 재생하며 위젯을 갱신만 한다(§4: 재분석 없음).
레이아웃: 상단바(뒤로/곡명/BPM) · 코드 HUD(현재 + 다음 가이드 + 카운트인)
        · 리프연습 토글 · 피아노 · 리프 뷰(연습 시) · 스크럽 · 재생
"""
from __future__ import annotations

import bisect

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal

from player.timeline import Timeline
from player.playhead import Playhead
from player.note_synth import NotePlayer
from analyze.theory import degree_number
from ml.model import load_model
from ml.generate import bake_examples

from gui import theme as T
from gui.widgets.piano import PianoWidget
from gui.widgets.scrub_bar import ScrubBar
from gui.widgets.mini_guide import MiniGuide
from gui.widgets.riff_view import RiffView
from gui.widgets.countin import CountIn

# 코드/가이드를 재생 위치보다 앞당겨 표시하는 보정값(초). 0 = 보정 없음.
SYNC_LOOKAHEAD_SEC = 0.0


class MainScreen(QWidget):
    backToScoreRequested = pyqtSignal()
    backToLinkRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl: Timeline | None = None
        self.playhead: Playhead | None = None
        self.note_player = NotePlayer(self)
        self._last_idx = -1
        self._mode = "guide"               # guide ↔ practice(리프연습)
        self._ml_model = load_model()      # 부트스트랩/학습 모델(없으면 규칙 폴백)
        # 재생 헤드에 동기화된 리프 이벤트(절대초, midi) — 일시정지/시킹과 함께 동작(§2)
        self._riff_events: list[tuple[float, int]] = []
        self._riff_times: list[float] = []
        self._riff_idx = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 14, 20, 14)
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
        self.bpm_lbl = QLabel("")
        self.bpm_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;")
        top.addWidget(self.bpm_lbl)
        root.addLayout(top)

        # ── 코드 HUD: 좌=현재 / 우=다음(텍스트+미니 가이드+카운트인) ──
        hud = QFrame()
        hud.setStyleSheet(
            f"QFrame{{background:{T.BG_INSET};border:1px solid {T.BORDER_SUBTLE};"
            f"border-radius:12px;}}")
        hl = QHBoxLayout(hud); hl.setContentsMargins(18, 12, 18, 12); hl.setSpacing(18)
        # 현재
        cur = QVBoxLayout(); cur.setSpacing(2)
        self.chord_lbl = QLabel("—")
        self.chord_lbl.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS_EN}';"
            "font-size:28px;font-weight:900;border:none;")
        cur.addWidget(self.chord_lbl)
        self.scale_lbl = QLabel("")
        self.scale_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';"
            "font-size:15px;font-weight:700;border:none;letter-spacing:1px;")
        cur.addWidget(self.scale_lbl)
        cur.addStretch(1)
        hl.addLayout(cur)
        # 가운데 빈칸: 리프연습 시 리프 가이드(현재↔다음 사이). OFF면 빈 공간.
        hl.addStretch(1)
        self.riff = RiffView()
        self.riff.setVisible(False)
        hl.addWidget(self.riff, 6)
        hl.addStretch(1)
        # 다음 (텍스트 + 미니 가이드 + 카운트인)
        nxt = QVBoxLayout(); nxt.setSpacing(4)
        self.next_lbl = QLabel("")
        self.next_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;border:none;")
        self.next_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        nxt.addWidget(self.next_lbl)
        self.next_guide = MiniGuide()
        self.next_guide.setFixedSize(220, 56)
        nxt.addWidget(self.next_guide)
        self.countin = CountIn()
        self.countin.setFixedWidth(220)
        nxt.addWidget(self.countin)
        hl.addLayout(nxt)
        root.addWidget(hud)

        # ── 리프연습 토글 (HUD 아래, 좌측 정렬, ON/OFF 버튼형) ──
        rrow = QHBoxLayout()
        self.riff_btn = QPushButton("리프연습")
        self.riff_btn.setCheckable(True)
        self.riff_btn.setFixedSize(150, 40)   # ON/OFF 토글해도 크기 불변(레이아웃 고정)
        self.riff_btn.clicked.connect(self._toggle_riff)
        rrow.addWidget(self.riff_btn)
        rrow.addStretch(1)
        root.addLayout(rrow)
        self._style_riff_btn()

        # ── 피아노 (리프연습과 무관하게 가만히 — 가이드 그대로) ──
        self.piano = PianoWidget()
        self.piano.notePlayed.connect(self.on_midi_note)
        root.addWidget(self.piano, 1)

        # ── 스크럽 ──
        self.scrub = ScrubBar()
        self.scrub.seekRequested.connect(self._on_seek)
        root.addWidget(self.scrub)

        # ── 재생/일시정지 (흰 원형, §6.1) ──
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(60, 60)
        self.play_btn.setStyleSheet(
            f"QPushButton{{background:{T.WHITE};color:{T.BG_BASE};border:none;"
            f"border-radius:30px;font-size:22px;font-weight:700;}}"
            f"QPushButton:hover{{background:{T.TEXT_BODY};}}")
        self.play_btn.clicked.connect(self._toggle_play)
        bottom.addWidget(self.play_btn)
        bottom.addStretch(1)
        root.addLayout(bottom)

    # ── 리프연습 토글 버튼 스타일 ────────────────────────────────
    def _style_riff_btn(self):
        on = (self._mode == "practice")
        self.riff_btn.setChecked(on)
        self.riff_btn.setText("리프연습  ●  ON" if on else "리프연습  ○  OFF")
        # 두 상태 동일 박스 모델(테두리 1px·폰트 동일) + 고정 크기 → 토글해도 안 밀림
        if on:
            bg, fg, border = T.WHITE, T.BG_BASE, T.WHITE
        else:
            bg, fg, border = "transparent", T.TEXT_PRIMARY, T.BORDER_ACTIVE
        self.riff_btn.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};border:1px solid {border};"
            f"border-radius:10px;font-size:13px;font-weight:700;}}")

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
        self.tl = tl
        self._last_idx = -1
        if not getattr(tl, "scale_riffs", None):   # 아직이면 1회 굽기(§8)
            bake_examples(tl, self._ml_model)
        self._build_riff_events()          # 리프를 곡에 함께 구움(§2)
        self._riff_idx = 0
        self.playhead = Playhead(tl.content_end(), tl.audio_ref, self)
        self.playhead.positionChanged.connect(self._on_tick)
        self.playhead.stateChanged.connect(self._on_state)

        self.song_lbl.setText(tl.title or tl.audio_ref or "내 곡")
        self.bpm_lbl.setText(f"{tl.key}  ·  {tl.bpm:.0f} BPM")
        self.scrub.set_timeline(tl)
        self.scrub.set_position(0.0)
        self._render_at(0.0)

    def pause(self):
        if self.playhead:
            self.playhead.pause()

    # ── 리프연습 ON/OFF ──────────────────────────────────────────
    def _toggle_riff(self):
        self._mode = "practice" if self._mode != "practice" else "guide"
        self._style_riff_btn()
        practice = (self._mode == "practice")
        self.riff.setVisible(practice)
        if practice:
            seg = self._current_segment()
            if seg and self.tl:
                self.riff.set_segment(seg, self.tl.bpm, self.tl.time_sig_beats())
            # 현재 위치부터 리프 재생(과거 음은 건너뜀)
            self._build_riff_events()
            self._seek_riff_idx(self.playhead.position_sec() if self.playhead else 0.0)
        else:
            self.riff.clear()

    # ── 재생 제어 ────────────────────────────────────────────────
    def _toggle_play(self):
        if self.playhead:
            self.playhead.toggle()

    def _on_state(self, playing: bool):
        self.play_btn.setText("⏸" if playing else "▶")

    def _on_seek(self, sec: float):
        if self.playhead:
            self.playhead.seek(sec)
            self._render_at(sec)
            self._seek_riff_idx(sec)        # 리프 커서도 함께 점프

    def _on_tick(self, sec: float):
        self.scrub.set_position(sec)
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
        if idx < 0 or idx == self._last_idx:
            return
        self._last_idx = idx
        seg = self.tl.segments[idx]
        self.piano.set_scale(seg.note_set, seg.chord_tones())
        self.piano.set_degrees(
            {pc: degree_number(pc, seg.scale_root) for pc in seg.note_set})
        self.piano.set_pressed(set())
        self._update_hud(seg)
        # 리프연습: 새 구간 진입 시 리프 뷰만 갱신(재생은 _on_tick이 헤드 동기로 트리거)
        if self._mode == "practice":
            self.riff.set_segment(seg, self.tl.bpm, self.tl.time_sig_beats())

    def _update_hud(self, seg):
        self.chord_lbl.setText(seg.chord.name)
        self.scale_lbl.setText(seg.scale_name)
        nxt = self.tl.next_segment(seg)
        if nxt:
            self.next_lbl.setText(f"다음 ▸  {nxt.chord.name}   {nxt.scale_name}")
            self.next_guide.set_scale(nxt.note_set, nxt.chord_tones(), nxt.scale_root)
        else:
            self.next_lbl.setText("")
            self.next_guide.clear()

    # ── 매 틱 라이브 갱신: 카운트인 + 리프 헤드 ──────────────────
    def _update_live(self, sec: float):
        if not self.tl or not self.tl.segments:
            return
        idx = self.tl.segment_index_at(sec)
        if idx < 0:
            return
        seg = self.tl.segments[idx]
        nxt = self.tl.next_segment(seg)
        if nxt is None:
            self.countin.set_remaining(None)
        else:
            beat = self.tl.beat_sec()
            self.countin.set_remaining((seg.end_sec - sec) / beat if beat else None)
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
