"""[3] 메인 화면 = 플레이어 — ScaleRiff (디자인 스펙 §6.1).

타임라인을 재생하며 위젯을 갱신만 한다(§4: 재분석 없음).
레이아웃: 상단바(뒤로/곡명/BPM) · 코드 HUD · 모드 pill · 피아노 · 피드백 · 스크럽 · 재생
"""
from __future__ import annotations

from functools import partial

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from player.timeline import Timeline
from player.playhead import Playhead
from player.note_synth import NotePlayer
from analyze.theory import degree_number
from ml.model import load_model
from ml.generate import bake_examples

from gui import theme as T
from gui.widgets.piano import PianoWidget
from gui.widgets.feedback import FeedbackPanel
from gui.widgets.scrub_bar import ScrubBar


class MainScreen(QWidget):
    backToScoreRequested = pyqtSignal()
    backToLinkRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl: Timeline | None = None
        self.playhead: Playhead | None = None
        self.note_player = NotePlayer(self)
        self._last_idx = -1
        self._mode = "guide"
        self._ml_model = load_model()      # 부트스트랩/학습 모델(없으면 규칙 폴백)
        self._play_along = False

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

        # ── 코드 HUD ──
        hud = QFrame()
        hud.setStyleSheet(
            f"QFrame{{background:{T.BG_INSET};border:1px solid {T.BORDER_SUBTLE};"
            f"border-radius:12px;}}")
        hl = QHBoxLayout(hud); hl.setContentsMargins(18, 12, 18, 12)
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
        hl.addLayout(cur)
        hl.addStretch(1)
        self.next_lbl = QLabel("")
        self.next_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;border:none;")
        self.next_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hl.addWidget(self.next_lbl)
        root.addWidget(hud)

        # ── ML 예시 + 모드 토글 줄 ──
        mrow = QHBoxLayout()
        self.listen_btn = QPushButton("🎧 듣기")
        self.listen_btn.setStyleSheet(T.qss_outline_btn())
        self.listen_btn.clicked.connect(self._on_listen)
        mrow.addWidget(self.listen_btn)
        self.along_btn = QPushButton("👥 같이 연주")
        self.along_btn.clicked.connect(self._toggle_play_along)
        mrow.addWidget(self.along_btn)
        mrow.addStretch(1)
        self.mode_btn = QPushButton("가이드  ●  퀴즈")
        self.mode_btn.clicked.connect(self._toggle_mode)
        mrow.addWidget(self.mode_btn)
        root.addLayout(mrow)
        self._style_mode_btn()
        self._style_along_btn()

        # ── 피아노 ──
        self.piano = PianoWidget()
        self.piano.notePlayed.connect(self.on_midi_note)
        root.addWidget(self.piano, 1)

        # ── 피드백 ──
        self.feedback = FeedbackPanel()
        fbframe = QFrame()
        fbframe.setStyleSheet(
            f"QFrame{{background:{T.BG_SURFACE};border:1px solid {T.BORDER_SUBTLE};"
            f"border-radius:10px;}}")
        fl = QVBoxLayout(fbframe); fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(self.feedback)
        root.addWidget(fbframe)

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

    # ── 모드 pill 스타일 ─────────────────────────────────────────
    def _style_mode_btn(self):
        if self._mode == "quiz":
            self.mode_btn.setText("가이드  ○━●  퀴즈")
        else:
            self.mode_btn.setText("가이드  ●━○  퀴즈")
        self.mode_btn.setStyleSheet(
            f"QPushButton{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_PRIMARY};"
            f"border:1px solid {T.BORDER_ACTIVE};border-radius:16px;"
            f"padding:7px 18px;font-size:13px;}}")

    def _style_along_btn(self):
        if self._play_along:
            self.along_btn.setText("👥 같이 연주 ●")
            self.along_btn.setStyleSheet(
                f"QPushButton{{background:{T.WHITE};color:{T.BG_BASE};border:none;"
                f"border-radius:10px;padding:11px 16px;font-size:14px;font-weight:700;}}")
        else:
            self.along_btn.setText("👥 같이 연주")
            self.along_btn.setStyleSheet(T.qss_outline_btn())

    # ── ML 예시 재생 ─────────────────────────────────────────────
    def _current_segment(self):
        if not self.tl or self.playhead is None:
            return None
        return self.tl.segment_at(self.playhead.position_sec())

    def _on_listen(self):
        self._play_example(self._current_segment())

    def _toggle_play_along(self):
        self._play_along = not self._play_along
        self._style_along_btn()
        if self._play_along and self.playhead and self.playhead.is_playing():
            self._play_example(self._current_segment())

    @staticmethod
    def _swing(beat_pos: float) -> float:
        """오프비트 8분음표를 약간 늦춰 스윙 느낌(16칸 직선 표현 유지, 재생만)."""
        whole = int(beat_pos)
        frac = beat_pos - whole
        if abs(frac - 0.5) < 0.05:
            frac = 0.62
        return whole + frac

    def _play_example(self, seg):
        if not seg or not getattr(seg, "example", None) or not self.tl:
            return
        beat_ms = 60000.0 / self.tl.bpm if self.tl.bpm > 0 else 500.0
        for n in seg.example:
            t = int(self._swing(n["beat_pos"]) * beat_ms)
            QTimer.singleShot(t, partial(self.note_player.play_note, n["midi"]))

    # ── 타임라인 로드 ────────────────────────────────────────────
    def set_timeline(self, tl: Timeline):
        if self.playhead:
            self.playhead.pause()
        self.tl = tl
        self._last_idx = -1
        bake_examples(tl, self._ml_model)   # 연습 진입 시 1회 example 굽기(§4)
        self.playhead = Playhead(tl.content_end(), tl.audio_ref, self)
        self.playhead.positionChanged.connect(self._on_tick)
        self.playhead.stateChanged.connect(self._on_state)

        self.song_lbl.setText(tl.title or tl.audio_ref or "내 곡")
        self.bpm_lbl.setText(f"{tl.key}  ·  {tl.bpm:.0f} BPM")
        self.scrub.set_timeline(tl)
        self.scrub.set_position(0.0)
        self.feedback.reset()
        self._render_at(0.0)

    def pause(self):
        if self.playhead:
            self.playhead.pause()

    # ── 모드 ─────────────────────────────────────────────────────
    def _toggle_mode(self):
        self._mode = "quiz" if self._mode == "guide" else "guide"
        self.piano.set_mode(self._mode)
        self.piano.clear_reveal()
        self._style_mode_btn()

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

    def _on_tick(self, sec: float):
        self.scrub.set_position(sec)
        self._render_at(sec)

    # ── 상태 → UI 렌더 ───────────────────────────────────────────
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
        self.piano.clear_reveal()
        self.piano.set_pressed(set())
        self.feedback.reset()
        self._update_hud(seg)
        # 같이 연주: 새 구간 진입 시 그 구간 예시를 동기 재생
        if self._play_along and self.playhead and self.playhead.is_playing():
            self._play_example(seg)

    def _update_hud(self, seg):
        self.chord_lbl.setText(seg.chord.name)
        self.scale_lbl.setText(seg.scale_name)
        nxt = self.tl.next_segment(seg)
        self.next_lbl.setText(
            f"다음 ▸  {nxt.chord.name}\n{nxt.scale_name}" if nxt else "")

    # ── 입력 콜백 ────────────────────────────────────────────────
    def on_midi_note(self, midi: int, is_on: bool):
        if not self.tl or self.playhead is None:
            return
        pressed = set(self.piano._pressed)
        if is_on:
            pressed.add(midi)
            self.note_player.play_note(midi)
            if self._mode == "quiz":
                self.piano.reveal(midi)
            seg = self.tl.segment_at(self.playhead.position_sec())
            if seg:
                self.feedback.show_note(midi, seg.chord, seg.note_set,
                                        seg.chord.chord_tones())
        else:
            pressed.discard(midi)
        self.piano.set_pressed(pressed)
