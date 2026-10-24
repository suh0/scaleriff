"""[2] 악보 화면 — ScaleRiff. 사용된 스케일·생성 리프 확인(+재생성).

- 곡맥락 리스트: 스케일 종류별 행(사용 코드·마디 범위) — 눌러 리프 확인.
- 리프는 세로 건반이 붙은 피아노롤(RiffRoll)로 표시.
- 마디별 코드 목록·수정·루프 지정은 박자 조정 화면(beat_screen).
- '연습 시작'으로 메인 플레이어 진입.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea
)
from PyQt6.QtCore import pyqtSignal, QTimer, Qt

from gui import theme as T
from gui.anim import stagger
from gui.widgets.flow_header import FlowHeader
from gui.widgets.elided_label import ElidedLabel
from gui.widgets.riff_roll import RiffRoll
from ml.generate import rebake_kind
from player.note_synth import shared_player


class ScoreScreen(QWidget):
    practiceRequested = pyqtSignal()
    backToBeatRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl = None
        self._model = None      # ML 모델(수동 수정 시 리프 재생성용)
        self.note_player = shared_player()           # 리프 미리듣기(전역 공유)
        self._riff_timers: list[QTimer] = []
        content = T.compact_content(self)
        root = QVBoxLayout(content)
        root.setContentsMargins(T.PAD_H, T.PAD_V, T.PAD_H, T.PAD_V)
        root.setSpacing(12)
        root.addWidget(FlowHeader(4))

        top = QHBoxLayout()
        self.link_btn = QPushButton("← 코드 편집")
        self.link_btn.setStyleSheet(T.qss_ghost_btn())
        self.link_btn.clicked.connect(self.backToBeatRequested.emit)
        top.addWidget(self.link_btn)
        self.title = ElidedLabel("리프 확인")
        self.title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS}';"
            "font-size:18px;font-weight:700;")
        top.addSpacing(8)
        top.addWidget(self.title, 1)
        self.key_lbl = QLabel("")
        self.key_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;")
        top.addWidget(self.key_lbl)
        root.addLayout(top)

        # ── 곡맥락 리스트: 스케일 종류별 행(사용 코드 · 마디 범위) ──
        self.riffs_title = QLabel("사용된 스케일")
        self.riffs_title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_MONO}';"
            "font-size:13px;font-weight:700;")
        body = QHBoxLayout()
        body.setSpacing(24)
        sidebar = QWidget()
        sidebar.setMinimumWidth(210)
        sidebar.setMaximumWidth(290)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        side.addWidget(self.riffs_title)
        self.kinds_row = QVBoxLayout()
        self.kinds_row.setSpacing(6)
        self._kinds_wrap = QWidget()
        self._kinds_wrap.setObjectName("scaleList")
        self._kinds_wrap.setStyleSheet(f"QWidget#scaleList{{background:{T.BG_BASE};}}")
        self._kinds_wrap.setLayout(self.kinds_row)
        self.kinds_row.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.kinds_scroll = QScrollArea()
        self.kinds_scroll.setWidgetResizable(True)
        self.kinds_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.kinds_scroll.setWidget(self._kinds_wrap)
        side.addWidget(self.kinds_scroll, 1)
        body.addWidget(sidebar, 1)
        preview = QVBoxLayout()
        preview.setSpacing(12)

        # ── 선택한 스케일의 리프 — 세로 건반이 붙은 피아노롤 ──
        riff_head = QHBoxLayout()
        self.riff_lbl = QLabel("생성된 리프 (C 기준)")
        self.riff_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:11px;")
        riff_head.addWidget(self.riff_lbl)
        riff_head.addStretch(1)
        self.play_riff_btn = QPushButton("▶ 리프 듣기")
        self.play_riff_btn.setStyleSheet(T.qss_ghost_btn())
        self.play_riff_btn.clicked.connect(self._play_riff)
        riff_head.addWidget(self.play_riff_btn)
        self.regen_btn = QPushButton("다시 만들기")
        self.regen_btn.setStyleSheet(T.qss_ghost_btn())
        self.regen_btn.clicked.connect(self._regen_riff)
        riff_head.addWidget(self.regen_btn)
        preview.addLayout(riff_head)
        self.roll = RiffRoll()
        preview.addWidget(self.roll)
        self.empty_lbl = QLabel("확인할 리프가 없어요. 코드 편집에서 코드를 확인하거나 연습을 시작하세요.")
        self.empty_lbl.setWordWrap(True)
        self.empty_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:14px;")
        preview.addWidget(self.empty_lbl)
        preview.addStretch(1)
        body.addLayout(preview, 3)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        footnote = QLabel("스케일을 고르고 리프를 들어본 뒤, 직접 연주해보세요.")
        footnote.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        footnote.setWordWrap(True)
        bottom.addWidget(footnote, 1)
        self.go_btn = QPushButton("연습 시작 ▶")
        self.go_btn.setStyleSheet(T.qss_primary_btn())
        self.go_btn.clicked.connect(self.practiceRequested.emit)
        bottom.addWidget(self.go_btn)
        root.addLayout(bottom)

    def showEvent(self, e):
        super().showEvent(e)
        stagger([self.riffs_title, self._kinds_wrap, self.roll, self.go_btn])

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
                    f"border-radius:7px;padding:8px 14px;font-size:12px;font-weight:700;}}"
                    f"QPushButton:focus{{border:1px solid {T.BORDER_ACTIVE};}}")
        return (f"QPushButton{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_BODY};"
                f"border:1px solid {T.BORDER_DEFAULT};border-radius:7px;"
                f"padding:8px 14px;font-size:12px;text-align:left;}}"
                f"QPushButton:hover,QPushButton:focus{{border:1px solid {T.BORDER_ACTIVE};color:{T.TEXT_PRIMARY};}}")

    def _kind_context(self, kind: str) -> str:
        """곡맥락 — 그 스케일이 쓰인 코드(등장순)."""
        chords: list[str] = []
        for s in getattr(self.tl, "segments", None) or []:
            if s.scale and s.scale.kind == kind and s.chord.name not in chords:
                chords.append(s.chord.name)
        return ", ".join(chords)

    def _build_riffs(self):
        while self.kinds_row.count():
            it = self.kinds_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._kind_btns = {}
        self._sel_kind = None
        riffs = getattr(self.tl, "scale_riffs", None) or {}
        widgets = (self.riffs_title, self.kinds_scroll, self.riff_lbl,
                   self.roll, self.regen_btn, self.play_riff_btn)
        self.empty_lbl.setVisible(not bool(riffs))
        if not riffs:
            for wdg in widgets:
                wdg.hide()
            return
        for wdg in widgets:
            wdg.show()
        for kind, data in riffs.items():
            ctx = self._kind_context(kind)
            row = QPushButton(f"{kind} — {ctx}" if ctx else kind)
            row.setToolTip(row.text())
            row.setMinimumWidth(0)
            row.setMaximumWidth(270)
            row.setText(row.fontMetrics().elidedText(row.text(), Qt.TextElideMode.ElideRight, 236))
            row.setStyleSheet(self._chip_qss(False))
            row.clicked.connect(lambda _, k=kind: self._show_riff(k))
            self.kinds_row.addWidget(row)
            self._kind_btns[kind] = row
        self._show_riff(next(iter(riffs)))   # 첫 스케일 기본 선택

    def _show_riff(self, kind: str):
        riffs = getattr(self.tl, "scale_riffs", None) or {}
        data = riffs.get(kind)
        if not data:
            return
        for k, btn in self._kind_btns.items():
            btn.setStyleSheet(self._chip_qss(k == kind))
        self._sel_kind = kind
        # C(루트0) 기준 — 거터 건반이 스케일 가이드를 겸함
        self.roll.set_riff(
            data.get("notes", []), data.get("note_set", []),
            data.get("chord_tones", []),
            self.tl.time_sig_beats(), data.get("n_bars", 1))

    def _regen_riff(self):
        """선택한 스케일 종류의 리프를 다른 변주로 재생성(§8) + 뷰 갱신."""
        if self.tl is None or not self._sel_kind:
            return
        rebake_kind(self.tl, self._model, self._sel_kind)
        self._show_riff(self._sel_kind)

    LEAD_MS = 250   # 첫 음 리드인 — 장치 예열이 끝난 뒤 정확한 간격으로 시작

    def _play_riff(self):
        """선택한 리프를 곡 BPM으로 미리듣기(신스 note-on 예약)."""
        self._stop_riff()
        riffs = getattr(self.tl, "scale_riffs", None) or {}
        data = riffs.get(self._sel_kind) or {}
        beat_ms = 60000.0 / (self.tl.bpm if self.tl and self.tl.bpm > 0 else 120)
        notes = data.get("notes", [])
        self.note_player.preload({n["midi"] for n in notes})  # 리드인 동안 로드
        self.note_player.warmup()       # 무음 예열(첫 음 몰림 방지)
        for n in notes:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(lambda m=n["midi"]: self.note_player.play_note(m))
            t.start(self.LEAD_MS + int(n["beat_pos"] * beat_ms))
            self._riff_timers.append(t)

    def _stop_riff(self):
        for t in self._riff_timers:
            t.stop()
            t.deleteLater()
        self._riff_timers.clear()
