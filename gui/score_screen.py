"""[2] 악보 화면 — ScaleRiff. 스케일 리프 확인 + 루프/스플릿 보정.

- 상단 칩: 스케일 '종류'로 통일(도리안·펜타토닉 …) — 눌러 리프 확인.
- 마디별 코드 목록·수정은 박자 조정 화면(beat_screen)으로 이동.
- '연습 시작'으로 메인 플레이어 진입.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox
)
from PyQt6.QtCore import pyqtSignal

from gui import theme as T
from gui.widgets.riff_view import RiffView
from gui.widgets.mini_guide import MiniGuide


class ScoreScreen(QWidget):
    practiceRequested = pyqtSignal()
    backToLinkRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl = None
        self._model = None      # ML 모델(수동 수정 시 리프 재생성용)
        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_H, T.PAD_V, T.PAD_H, T.PAD_V)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.link_btn = QPushButton("← 링크")
        self.link_btn.setStyleSheet(T.qss_ghost_btn())
        self.link_btn.clicked.connect(self.backToLinkRequested.emit)
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
        # ── 분석 보정(§3.5): 루프 주기 override + 스플릿 포인트 ──
        combo_qss = (
            f"QComboBox{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_BODY};"
            f"border:1px solid {T.BORDER_DEFAULT};border-radius:8px;"
            f"padding:4px 10px;font-family:'{T.FONT_MONO}';font-size:12px;}}"
            f"QComboBox QAbstractItemView{{background:{T.BG_SURFACE_ALT};"
            f"color:{T.TEXT_BODY};selection-background-color:{T.BORDER_DEFAULT};}}")
        self.loop_box = QComboBox()
        self.loop_box.setStyleSheet(combo_qss)
        top.addSpacing(8)
        top.addWidget(self.loop_box)
        self.loop_box.currentIndexChanged.connect(self._on_loop_changed)
        root.addLayout(top)

        hint = QLabel("칩을 눌러 스케일 리프를 확인하고, 루프 주기를 보정하세요. "
                      "코드 수정은 이전(박자 조정) 화면에서.")
        hint.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        root.addWidget(hint)

        # ── 사용된 스케일 종류(가로 칩) ──
        self.riffs_title = QLabel("사용된 스케일")
        self.riffs_title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_MONO}';"
            "font-size:13px;font-weight:700;")
        root.addWidget(self.riffs_title)
        self.kinds_row = QHBoxLayout()
        self.kinds_row.setSpacing(8)
        kinds_wrap = QWidget()
        kinds_wrap.setLayout(self.kinds_row)
        root.addWidget(kinds_wrap)

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
        self.riff_lbl = QLabel("생성된 리프")
        self.riff_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:11px;")
        right.addWidget(self.riff_lbl)
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

    # ── 로드/렌더 ────────────────────────────────────────────────
    def set_timeline(self, tl, model=None):
        self.tl = tl
        self._model = model
        self.title.setText(tl.title or "코드 진행")
        self.key_lbl.setText(f"{tl.key}  ·  {tl.bpm:.0f} BPM")
        self._fill_correction_boxes(tl)
        self._build_riffs()

    # ── 분석 보정 콤보(§3.5) — 값 저장만, 재분석 없음(엔진은 연습 진입 시 반영) ──
    def _fill_correction_boxes(self, tl):
        self.loop_box.blockSignals(True)
        self.loop_box.clear()
        self.loop_box.addItem(f"루프: 감지값 ({tl.loop_len}마디)", 0)
        for n in (1, 2, 4, 8, 16):
            self.loop_box.addItem(f"루프: {n}마디", n)
        idx = self.loop_box.findData(tl.loop_override)
        self.loop_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.loop_box.blockSignals(False)

    def _on_loop_changed(self):
        if self.tl is not None:
            self.tl.loop_override = self.loop_box.currentData() or 0

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
                   self.riff_lbl, self.sel_riff)
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
