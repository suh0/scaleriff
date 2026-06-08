"""[2] 악보 화면 — ScaleRiff. 분석 후 마디별 코드 진행을 한눈에.

- 전체 마디를 악보처럼 격자로(마디마다 코드).
- 여러 스케일 가능한 구간은 골드 테두리 강조 → 클릭해 적용 스케일 선택.
- 상단 칩: 스케일 '종류'로 통일(도리안·펜타토닉 …).
- '연습 시작'으로 메인 플레이어 진입.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QMenu, QFrame
)
from PyQt6.QtGui import QCursor
from PyQt6.QtCore import Qt, pyqtSignal

from gui import theme as T

BARS_PER_ROW = 8


class ScoreScreen(QWidget):
    practiceRequested = pyqtSignal()
    backToLinkRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 18, 28, 18)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.link_btn = QPushButton("← 링크")
        self.link_btn.setStyleSheet(T.qss_ghost_btn())
        self.link_btn.clicked.connect(self.backToLinkRequested.emit)
        top.addWidget(self.link_btn)
        self.title = QLabel("코드 진행")
        self.title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SERIF_KR}';"
            "font-size:18px;font-weight:bold;")
        top.addSpacing(8)
        top.addWidget(self.title)
        top.addStretch(1)
        self.key_lbl = QLabel("")
        self.key_lbl.setStyleSheet(
            f"color:{T.TEXT_ACCENT};font-family:'{T.FONT_MONO}';font-size:12px;")
        top.addWidget(self.key_lbl)
        root.addLayout(top)

        hint = QLabel("강조된 마디는 여러 스케일이 가능해요 — 눌러서 고르세요. "
                      "위 칩으로 한 종류로 통일할 수도 있어요.")
        hint.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        root.addWidget(hint)

        self.chips_row = QHBoxLayout()
        self.chips_row.setSpacing(6)
        chips_wrap = QWidget()
        chips_wrap.setLayout(self.chips_row)
        root.addWidget(chips_wrap)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(
            "QScrollArea{border:none;background:transparent;}"
            "QScrollArea > QWidget > QWidget{background:transparent;}")
        self.holder = QWidget()
        self.holder.setStyleSheet("background:transparent;")
        self.grid = QGridLayout(self.holder)
        self.grid.setSpacing(8)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(self.holder)
        root.addWidget(self.scroll, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.go_btn = QPushButton("연습 시작 ▶")
        self.go_btn.setStyleSheet(T.qss_primary_btn())
        self.go_btn.clicked.connect(self.practiceRequested.emit)
        bottom.addWidget(self.go_btn)
        bottom.addStretch(1)
        root.addLayout(bottom)

    # ── 로드/렌더 ────────────────────────────────────────────────
    def set_timeline(self, tl):
        self.tl = tl
        self.title.setText(tl.title or "코드 진행")
        self.key_lbl.setText(f"{tl.key}  ·  {tl.bpm:.0f} BPM")
        self._build_chips()
        self._build_grid()

    def _build_chips(self):
        while self.chips_row.count():
            it = self.chips_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        lab = QLabel("종류 통일:")
        lab.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        self.chips_row.addWidget(lab)
        for kind in self.tl.available_scales:
            chip = QPushButton(kind)
            chip.setStyleSheet(
                f"QPushButton{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_BODY};"
                f"border:1px solid {T.BORDER_DEFAULT};border-radius:14px;"
                f"padding:5px 12px;font-size:12px;}}"
                f"QPushButton:hover{{border:1px solid {T.BORDER_ACTIVE};color:{T.TEXT_PRIMARY};}}")
            chip.clicked.connect(lambda _, k=kind: self._apply_kind(k))
            self.chips_row.addWidget(chip)
        self.chips_row.addStretch(1)

    def _apply_kind(self, kind: str):
        self.tl.apply_kind(kind)
        self._build_grid()

    def _build_grid(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not self.tl:
            return
        for col in range(BARS_PER_ROW):
            self.grid.setColumnStretch(col, 1)
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
        multi = bool(seg and seg.has_options())
        chord_txt = seg.chord.name if (seg and is_new_chord) else "／"
        scale_txt = seg.scale_name if (seg and seg.scale) else ""

        cell = QFrame()
        border = T.BORDER_ACTIVE if multi else T.BORDER_DEFAULT
        bg = T.BG_SURFACE if multi else T.BG_INSET
        cell.setStyleSheet(
            f"QFrame{{background:{bg};border:2px solid {border};border-radius:8px;}}")
        cell.setFixedHeight(60)
        v = QVBoxLayout(cell); v.setContentsMargins(8, 5, 8, 5); v.setSpacing(1)
        bar_lbl = QLabel(f"{bar + 1}")
        bar_lbl.setStyleSheet(
            f"color:{T.TEXT_DIM};font-family:'{T.FONT_MONO}';font-size:9px;border:none;")
        v.addWidget(bar_lbl)
        c = QLabel(chord_txt)
        c.setStyleSheet(
            f"color:{T.TEXT_PRIMARY if is_new_chord else T.TEXT_DIM};"
            f"font-family:'{T.FONT_SERIF}';font-size:16px;font-weight:bold;border:none;")
        v.addWidget(c)
        s = QLabel(scale_txt)
        s.setStyleSheet(
            f"color:{T.TEXT_ACCENT if multi else T.TEXT_MUTED};"
            f"font-family:'{T.FONT_MONO}';font-size:10px;border:none;")
        v.addWidget(s)

        if multi:
            cell.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            cell.mousePressEvent = lambda e, sg=seg: self._choose(sg)
        return cell

    def _choose(self, seg):
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu{{background:{T.BG_SURFACE};color:{T.TEXT_BODY};"
            f"border:1px solid {T.BORDER_DEFAULT};}}"
            f"QMenu::item:selected{{background:{T.BORDER_DEFAULT};color:{T.TEXT_PRIMARY};}}")
        for i, opt in enumerate(seg.candidates):
            mark = " ✓" if i == seg.active else ""
            act = menu.addAction(f"{opt.name}  ({len(opt.note_set)}음){mark}")
            act.triggered.connect(lambda _, idx=i, sg=seg: self._apply_choice(sg, idx))
        menu.exec(QCursor.pos())

    def _apply_choice(self, seg, idx: int):
        seg.active = idx
        self._build_grid()
