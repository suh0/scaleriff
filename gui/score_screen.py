"""[2] 악보 화면 — ScaleRiff. 사용된 스케일·생성 리프 확인(+재생성).

- 상단 칩: 스케일 '종류'로 통일(도리안·펜타토닉 …) — 눌러 리프 확인.
- 마디별 코드 목록·수정·루프 지정은 박자 조정 화면(beat_screen).
- '연습 시작'으로 메인 플레이어 진입.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PyQt6.QtCore import pyqtSignal, QTimer

from gui import theme as T
from gui.anim import stagger
from gui.widgets.riff_view import RiffView
from gui.widgets.mini_guide import MiniGuide
from ml.generate import rebake_kind
from player.note_synth import NotePlayer


class ScoreScreen(QWidget):
    practiceRequested = pyqtSignal()
    backToBeatRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl = None
        self._model = None      # ML 모델(수동 수정 시 리프 재생성용)
        self.note_player = NotePlayer(self)          # 리프 미리듣기
        self._riff_timers: list[QTimer] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(56, 40, 56, 40)   # 여유 있는 패딩
        root.setSpacing(16)

        top = QHBoxLayout()
        self.link_btn = QPushButton("← 박자 조정")
        self.link_btn.setStyleSheet(T.qss_ghost_btn())
        self.link_btn.clicked.connect(self.backToBeatRequested.emit)
        top.addWidget(self.link_btn)
        self.title = QLabel("코드 진행")
        self.title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS}';"
            "font-size:18px;font-weight:700;")
        top.addSpacing(8)
        top.addWidget(self.title)
        top.addStretch(1)
        self.key_lbl = QLabel("")
        self.key_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;")
        top.addWidget(self.key_lbl)
        root.addLayout(top)

        # ── 사용된 스케일 종류(가로 칩) ──
        self.riffs_title = QLabel("사용된 스케일")
        self.riffs_title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_MONO}';"
            "font-size:13px;font-weight:700;")
        root.addWidget(self.riffs_title)
        self.kinds_row = QHBoxLayout()
        self.kinds_row.setSpacing(8)
        self._kinds_wrap = QWidget()
        self._kinds_wrap.setLayout(self.kinds_row)
        root.addWidget(self._kinds_wrap)

        # ── 선택한 스케일: (왼쪽) C 기준 스케일 가이드 / (오른쪽) 생성된 리프 ──
        #   두 위젯 모두 비율을 유지(MiniGuide=레터박스, RiffView=박자 격자).
        sel_row = QHBoxLayout(); sel_row.setSpacing(16)
        left = QVBoxLayout(); left.setSpacing(4)
        self.guide_lbl = QLabel("C 기준 스케일 가이드")
        self.guide_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:11px;")
        left.addWidget(self.guide_lbl)
        self.sel_guide = MiniGuide()
        self.sel_guide.setFixedHeight(130)
        left.addWidget(self.sel_guide)
        sel_row.addLayout(left, 4)
        right = QVBoxLayout(); right.setSpacing(4)
        riff_head = QHBoxLayout()
        self.riff_lbl = QLabel("생성된 리프")
        self.riff_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:11px;")
        riff_head.addWidget(self.riff_lbl)
        riff_head.addStretch(1)
        self.play_riff_btn = QPushButton("▶ 리프 듣기")
        self.play_riff_btn.setStyleSheet(T.qss_ghost_btn())
        self.play_riff_btn.clicked.connect(self._play_riff)
        riff_head.addWidget(self.play_riff_btn)
        self.regen_btn = QPushButton("리프 재생성 ↻")
        self.regen_btn.setStyleSheet(T.qss_ghost_btn())
        self.regen_btn.clicked.connect(self._regen_riff)
        riff_head.addWidget(self.regen_btn)
        right.addLayout(riff_head)
        self.sel_riff = RiffView()
        self.sel_riff.setFixedHeight(130)
        right.addWidget(self.sel_riff)
        sel_row.addLayout(right, 6)
        root.addLayout(sel_row)

        root.addStretch(1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.go_btn = QPushButton("연습 시작 ▶")
        self.go_btn.setStyleSheet(T.qss_primary_btn())
        self.go_btn.clicked.connect(self.practiceRequested.emit)
        bottom.addWidget(self.go_btn)
        bottom.addStretch(1)
        root.addLayout(bottom)

    def showEvent(self, e):
        super().showEvent(e)
        stagger([self.riffs_title, self._kinds_wrap, self.sel_guide,
                 self.sel_riff, self.go_btn])

    def hideEvent(self, e):
        self._stop_riff()          # 화면 이탈 시 미리듣기 중단
        super().hideEvent(e)

    # ── 로드/렌더 ────────────────────────────────────────────────
    def set_timeline(self, tl, model=None):
        self.tl = tl
        self._model = model
        self.title.setText(tl.title or "코드 진행")
        self.key_lbl.setText(f"{tl.key}  ·  {tl.bpm:.0f} BPM")
        self._build_riffs()

    @staticmethod
    def _chip_qss(selected: bool) -> str:
        if selected:
            return (f"QPushButton{{background:{T.WHITE};color:{T.BG_BASE};border:none;"
                    f"border-radius:14px;padding:6px 14px;font-size:12px;font-weight:700;}}")
        return (f"QPushButton{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_BODY};"
                f"border:1px solid {T.BORDER_DEFAULT};border-radius:14px;"
                f"padding:6px 14px;font-size:12px;}}"
                f"QPushButton:hover{{border:1px solid {T.BORDER_ACTIVE};color:{T.TEXT_PRIMARY};}}")

    def _build_riffs(self):
        while self.kinds_row.count():
            it = self.kinds_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._kind_btns = {}
        self._sel_kind = None
        riffs = getattr(self.tl, "scale_riffs", None) or {}
        widgets = (self.riffs_title, self.guide_lbl, self.sel_guide,
                   self.riff_lbl, self.sel_riff, self.regen_btn,
                   self.play_riff_btn)
        if not riffs:
            for wdg in widgets:
                wdg.hide()
            return
        for wdg in widgets:
            wdg.show()
        for kind, data in riffs.items():
            quality = data.get("quality", "")
            chip = QPushButton(f"{quality} ({kind})" if quality else kind)
            chip.setStyleSheet(self._chip_qss(False))
            chip.clicked.connect(lambda _, k=kind: self._show_riff(k))
            self.kinds_row.addWidget(chip)
            self._kind_btns[kind] = chip
        self.kinds_row.addStretch(1)
        self._show_riff(next(iter(riffs)))   # 첫 스케일 기본 선택

    def _show_riff(self, kind: str):
        riffs = getattr(self.tl, "scale_riffs", None) or {}
        data = riffs.get(kind)
        if not data:
            return
        for k, btn in self._kind_btns.items():
            btn.setStyleSheet(self._chip_qss(k == kind))
        self._sel_kind = kind
        note_set = data.get("note_set", [])
        chord_tones = data.get("chord_tones", [])
        # C(루트0) 기준 스케일 가이드
        self.sel_guide.set_scale(note_set, chord_tones, 0)
        self.sel_riff.set_riff(
            data.get("notes", []), 0, note_set, chord_tones,
            self.tl.time_sig_beats(), data.get("n_bars", 1))

    def _regen_riff(self):
        """선택한 스케일 종류의 리프를 다른 변주로 재생성(§8) + 뷰 갱신."""
        if self.tl is None or not self._sel_kind:
            return
        rebake_kind(self.tl, self._model, self._sel_kind)
        self._show_riff(self._sel_kind)

    def _play_riff(self):
        """선택한 리프를 곡 BPM으로 미리듣기(신스 note-on 예약)."""
        self._stop_riff()
        riffs = getattr(self.tl, "scale_riffs", None) or {}
        data = riffs.get(self._sel_kind) or {}
        beat_ms = 60000.0 / (self.tl.bpm if self.tl and self.tl.bpm > 0 else 120)
        for n in data.get("notes", []):
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda m=n["midi"]: self.note_player.play_note(m))
            t.start(int(n["beat_pos"] * beat_ms))
            self._riff_timers.append(t)

    def _stop_riff(self):
        for t in self._riff_timers:
            t.stop()
            t.deleteLater()
        self._riff_timers.clear()
