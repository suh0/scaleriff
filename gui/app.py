"""메인 윈도우 — QStackedWidget 화면 흐름 (정의서 §6).

[0] 링크 입력 → [1] 분석 중 → [2] 악보(마디별 코드·스케일 선택) → [3] 메인(플레이어)
"""
from __future__ import annotations

from PyQt6.QtWidgets import QMainWindow, QStackedWidget
from PyQt6.QtGui import QFont
from PyQt6.QtCore import QSettings

from gui import theme as T
from gui.link_screen import LinkScreen
from gui.analyzing_screen import AnalyzingScreen
from gui.score_screen import ScoreScreen
from gui.main_screen import MainScreen
from ml.timeline_builder import build_timeline
from ml.generate import bake_examples


class AppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        T.load_fonts()                       # 번들 폰트 로드(있으면)
        base = QFont(T.FONT_SANS, 11)        # v4: Noto Sans KR 한글 기본
        base.setWeight(QFont.Weight.Medium)  # v4: light(300) 금지, 최소 Medium(500)
        self.setFont(base)
        self.setWindowTitle("ScaleRiff")
        self.resize(1040, 740)
        self.setStyleSheet(f"QMainWindow{{background:{T.BG_BASE};}}")

        self._settings = QSettings("graduation-project", "ScaleRiff")
        seen_onboarding = self._settings.value("seen_onboarding", False, type=bool)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.link_screen = LinkScreen(show_onboarding=not seen_onboarding)
        self.analyzing = AnalyzingScreen()
        self.score = ScoreScreen()
        self.main_screen = MainScreen()

        for w in (self.link_screen, self.analyzing, self.score, self.main_screen):
            self.stack.addWidget(w)

        self.link_screen.buildRequested.connect(self._start_build)
        self.analyzing.timelineReady.connect(self._on_timeline_ready)
        self.analyzing.backRequested.connect(lambda: self.stack.setCurrentWidget(self.link_screen))
        self.score.practiceRequested.connect(self._enter_main)
        self.score.backToLinkRequested.connect(self._go_link)
        self.main_screen.backToLinkRequested.connect(self._go_link)
        self.main_screen.backToScoreRequested.connect(self._go_score)

        self._timeline = None
        self._midi = None
        self._try_start_midi()

    # ── 빌드 흐름 ────────────────────────────────────────────────
    def _start_build(self, source):
        self._settings.setValue("seen_onboarding", True)
        self.stack.setCurrentWidget(self.analyzing)
        self.analyzing.start(build_timeline, source)

    def _on_timeline_ready(self, timeline):
        self._timeline = timeline
        # 스케일 종류당 1개 리프 굽기(§8) — 악보 화면에서 미리 보여주기 위해 여기서 1회.
        if not getattr(timeline, "scale_riffs", None):
            bake_examples(timeline, self.main_screen._ml_model)
        self.score.set_timeline(timeline, self.main_screen._ml_model)
        self.stack.setCurrentWidget(self.score)

    def _enter_main(self):
        self.main_screen.set_timeline(self._timeline)
        self.stack.setCurrentWidget(self.main_screen)

    # ── 뒤로가기 ─────────────────────────────────────────────────
    def _go_link(self):
        self.main_screen.pause()
        self.stack.setCurrentWidget(self.link_screen)

    def _go_score(self):
        self.main_screen.pause()
        if self._timeline:
            self.stack.setCurrentWidget(self.score)
        else:
            self.stack.setCurrentWidget(self.link_screen)

    # ── MIDI ─────────────────────────────────────────────────────
    def _try_start_midi(self):
        try:
            from player.midi_input import MidiInput
            self._midi = MidiInput()
            if self._midi.open_first_available():
                self._midi.note_received.connect(self.main_screen.on_midi_note)
                self._midi.start()
        except Exception:
            self._midi = None

    def closeEvent(self, e):
        if self._midi:
            self._midi.stop()
        if self.main_screen.playhead:
            self.main_screen.playhead.pause()
        super().closeEvent(e)
