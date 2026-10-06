"""메인 윈도우 — QStackedWidget 화면 흐름 (정의서 §6).

[0] 링크 입력 → [1] 분석 중 → [2a] 박자 조정 → [2] 악보(코드·스케일·루프)
→ [3] 메인(플레이어)
"""
from __future__ import annotations

import glob
import hashlib
import os

from PyQt6.QtWidgets import (
    QMainWindow, QStackedWidget, QFrame, QHBoxLayout, QLabel, QPushButton
)
from PyQt6.QtGui import QFont
from PyQt6.QtCore import QSettings, pyqtSignal

from player.timeline import Timeline
from ingest.audio_source import _cache_key, _is_url

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "cache")

from gui import theme as T
from gui.link_screen import LinkScreen
from gui.analyzing_screen import AnalyzingScreen
from gui.beat_screen import BeatScreen
from gui.score_screen import ScoreScreen
from gui.main_screen import MainScreen
from build.timeline_builder import build_timeline
from ml.generate import bake_examples


class AnalysisPill(QFrame):
    """상단 고정 알약 — 백그라운드 분석 진행(N%) → 완료 시 '연주하기' 활성."""
    playRequested = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame{{background:{T.BG_SURFACE};border:1px solid {T.BORDER_DEFAULT};"
            f"border-radius:16px;}}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 6, 10, 6)
        self.lbl = QLabel("분석 중… 0%")
        self.lbl.setStyleSheet(
            f"color:{T.TEXT_BODY};font-family:'{T.FONT_MONO}';"
            "font-size:12px;border:none;")
        lay.addWidget(self.lbl)
        self.play_btn = QPushButton("연주하기 ▶")
        self.play_btn.setStyleSheet(T.qss_ghost_btn())
        self.play_btn.clicked.connect(self.playRequested.emit)
        self.play_btn.hide()
        lay.addWidget(self.play_btn)
        self.hide()

    def set_progress(self, pct: int):
        self.lbl.setText(f"분석 중… {pct}%")

    def set_ready(self, title: str):
        self.lbl.setText(f"분석 완료 — {title[:20]}" if title else "분석 완료")
        self.play_btn.show()
        self.adjustSize()

    def set_failed(self):
        self.lbl.setText("분석 실패 — 링크 화면에서 다시 시도")
        self.play_btn.hide()
        self.adjustSize()


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
        self.beat = BeatScreen()
        self.score = ScoreScreen()
        self.main_screen = MainScreen()

        for w in (self.link_screen, self.analyzing, self.beat, self.score,
                  self.main_screen):
            self.stack.addWidget(w)

        self.link_screen.buildRequested.connect(self._start_build)
        self.analyzing.timelineReady.connect(self._on_timeline_ready)
        self.analyzing.backRequested.connect(lambda: self.stack.setCurrentWidget(self.link_screen))
        # 백그라운드 분석 대기(연습하며 기다리기) — 상단 알약
        self._pill = AnalysisPill(self)
        self._bg_wait = False
        self._pending_tl = None
        self.analyzing.backgroundRequested.connect(self._enter_bg_wait)
        self.analyzing.progressChanged.connect(self._pill.set_progress)
        self.analyzing.analysisFailed.connect(self._on_bg_failed)
        self._pill.playRequested.connect(self._play_pending)
        self.beat.proceedRequested.connect(self._enter_score)
        self.beat.backToLinkRequested.connect(self._go_link)
        self.score.practiceRequested.connect(self._enter_main)
        self.score.backToBeatRequested.connect(
            lambda: self.stack.setCurrentWidget(self.beat))
        self.main_screen.backToLinkRequested.connect(self._go_link)
        self.main_screen.backToScoreRequested.connect(self._go_score)

        self._timeline = None
        self._midi = None
        self.link_screen.set_save_dir(
            self._settings.value("save_dir", _CACHE_DIR, type=str))
        self._try_start_midi()

    # ── 빌드 흐름 ────────────────────────────────────────────────
    def _start_build(self, source):
        self._settings.setValue("seen_onboarding", True)
        # 저장된 세션(.json) → 분석 생략, 즉시 로드(§4: 한 번 구운 건 다시 안 굽는다)
        if source.lower().endswith(".json") and os.path.exists(source):
            try:
                self._open_timeline(Timeline.load_json(source))
                return
            except (OSError, KeyError, ValueError):
                pass    # 세션 파일이 아니면 일반 분석으로
        if self._bg_wait:
            return      # 백그라운드 분석 중엔 새 분석 시작 안 함(세션 열기만)
        self._pill.hide()    # 이전 실패 알약 정리
        if _is_url(source):
            cached = self._load_link_cache(source)
            if cached is not None:
                self._open_timeline(cached)
                return
        self.stack.setCurrentWidget(self.analyzing)
        self.analyzing.start(build_timeline, source)

    def _load_link_cache(self, source):
        # 기존 다운로드·세션 파일의 해시로 조회 — 별도 색인 없이 과거 세션도 재사용.
        for audio in glob.glob(os.path.join(glob.escape(_CACHE_DIR), f"dl_{_cache_key(source)}.*")):
            key = hashlib.md5(audio.encode("utf-8")).hexdigest()[:16]
            for directory in dict.fromkeys((self.link_screen.save_dir() or _CACHE_DIR,
                                            _CACHE_DIR)):
                try:
                    paths = glob.glob(os.path.join(glob.escape(directory), f"*_{key}.json"))
                    paths.sort(key=os.path.getmtime, reverse=True)
                except OSError:
                    continue
                for path in paths:
                    try:
                        tl = Timeline.load_json(path)
                        if (tl.audio_ref == audio and os.path.isfile(tl.audio_ref)
                                and os.path.isfile(tl.wav_ref) and tl.segments):
                            return tl
                    except (OSError, KeyError, ValueError, TypeError):
                        continue
        return None

    def _session_path(self, tl) -> str:
        d = self.link_screen.save_dir() or _CACHE_DIR
        key = hashlib.md5((tl.audio_ref or tl.title or "session")
                          .encode("utf-8")).hexdigest()[:16]
        name = "".join(c for c in (tl.title or "")[:40]
                       if c.isalnum() or c in " _-").strip()
        return os.path.join(d, f"{name or 'session'}_{key}.json")

    def _save_session(self, tl):
        try:
            d = self.link_screen.save_dir() or _CACHE_DIR
            os.makedirs(d, exist_ok=True)
            self._settings.setValue("save_dir", d)   # 다음 실행에도 유지
            tl.save_json(self._session_path(tl))
        except OSError:
            pass    # 저장 실패는 치명적이지 않음

    def _on_timeline_ready(self, timeline):
        if self._bg_wait:               # 연습하며 기다리는 중 — 화면 전환 없이 보관
            if not getattr(timeline, "scale_riffs", None):
                bake_examples(timeline, self.main_screen._ml_model)
            self._save_session(timeline)
            self._pending_tl = timeline
            self._pill.set_ready(timeline.title or "")
            self._place_pill()
            return
        self._open_timeline(timeline)

    def _open_timeline(self, timeline):
        self._timeline = timeline
        # 스케일 종류당 1개 리프 굽기(§8) — 악보 화면에서 미리 보여주기 위해 여기서 1회.
        if not getattr(timeline, "scale_riffs", None):
            bake_examples(timeline, self.main_screen._ml_model)
        self._save_session(timeline)     # 재분석 없이 불러올 세션 파일(캐시)
        self.beat.set_timeline(timeline, self.main_screen._ml_model)
        self.stack.setCurrentWidget(self.beat)

    # ── 백그라운드 분석 대기(연습하며 기다리기) ──────────────────
    def _enter_bg_wait(self):
        self._bg_wait = True
        self.link_screen.set_restricted(True)
        self._pill.set_progress(self.analyzing.bar.value())
        self._pill.play_btn.hide()
        self._pill.show()
        self._pill.raise_()
        self._place_pill()
        self.stack.setCurrentWidget(self.link_screen)

    def _play_pending(self):
        tl = self._pending_tl
        self._exit_bg_wait()
        if tl is not None:
            self._open_timeline(tl)

    def _on_bg_failed(self):
        if not self._bg_wait:
            return                      # 분석 화면에 이미 오류 표시됨
        self._pill.set_failed()
        self._place_pill()
        self._bg_wait = False
        self.link_screen.set_restricted(False)

    def _exit_bg_wait(self):
        self._bg_wait = False
        self._pending_tl = None
        self.link_screen.set_restricted(False)
        self._pill.hide()

    def _place_pill(self):
        self._pill.adjustSize()
        self._pill.move((self.width() - self._pill.width()) // 2, 10)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_pill()

    def _enter_score(self):
        self._timeline = self.beat.tl
        self.score.set_timeline(self._timeline, self.main_screen._ml_model)
        self.stack.setCurrentWidget(self.score)

    def _enter_main(self):
        self._save_session(self._timeline)   # 보정·수정 반영해 세션 갱신
        self.main_screen.set_timeline(self._timeline)
        self.stack.setCurrentWidget(self.main_screen)

    # ── 뒤로가기 ─────────────────────────────────────────────────
    def _go_link(self):
        self.main_screen.pause()
        self.beat.pause()
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
        self.beat.pause()
        super().closeEvent(e)
