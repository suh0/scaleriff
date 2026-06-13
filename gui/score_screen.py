"""[2] 악보 화면 — ScaleRiff. 분석 후 마디별 코드 진행을 한눈에.

- 전체 마디를 악보처럼 격자로(마디마다 코드).
- 여러 스케일 가능한 구간은 골드 테두리 강조 → 클릭해 적용 스케일 선택.
- 상단 칩: 스케일 '종류'로 통일(도리안·펜타토닉 …).
- '연습 시작'으로 메인 플레이어 진입.
"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QInputDialog, QFrame
)
from PyQt6.QtGui import QCursor
from PyQt6.QtCore import Qt, pyqtSignal

from gui import theme as T
from gui.widgets.riff_view import RiffView
from gui.widgets.mini_guide import MiniGuide
from analyze.theory import (
    parse_chord, scale_pcs, degree_for, diatonic_option, pc_name,
)
from player.timeline import ScaleOption
from ml.generate import bake_segment

BARS_PER_ROW = 8
# 수동 코드 수정 선택지(접미사). parse_chord가 인식하는 표기.
_EDIT_SUFFIXES = ["", "m", "7", "maj7", "m7", "m7b5", "dim", "6", "m6", "sus4"]


class ScoreScreen(QWidget):
    practiceRequested = pyqtSignal()
    backToLinkRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl = None
        self._model = None      # ML 모델(수동 수정 시 리프 재생성용)
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

        hint = QLabel("위 칩으로 스케일 리프를 확인하고, 아래 마디 칸을 누르면 코드를 "
                      "직접 고칠 수 있어요(인식이 틀렸을 때 보정).")
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
    def set_timeline(self, tl, model=None):
        self.tl = tl
        self._model = model
        self.title.setText(tl.title or "코드 진행")
        self.key_lbl.setText(f"{tl.key}  ·  {tl.bpm:.0f} BPM")
        self._build_riffs()
        self._build_grid()

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
        detour = bool(seg and seg.is_detour)   # 비다이아토닉(§3)
        chord_txt = seg.chord.name if (seg and is_new_chord) else "／"
        scale_txt = seg.scale_name if (seg and seg.scale) else ""

        cell = QFrame()
        if detour:                              # 비다이아토닉 → 빨강 강조
            border, bg = T.BADGE_OUT, T.BG_SURFACE
        else:
            border, bg = T.BORDER_DEFAULT, T.BG_INSET
        cell.setStyleSheet(
            f"QFrame{{background:{bg};border:2px solid {border};border-radius:8px;}}")
        cell.setFixedHeight(60)
        v = QVBoxLayout(cell); v.setContentsMargins(8, 5, 8, 5); v.setSpacing(1)
        bar_lbl = QLabel(f"{bar + 1}" + ("  ⚠ 비다이아토닉" if (detour and is_new_chord) else ""))
        bar_lbl.setStyleSheet(
            f"color:{T.BADGE_OUT if detour else T.TEXT_DIM};"
            f"font-family:'{T.FONT_MONO}';font-size:9px;border:none;")
        v.addWidget(bar_lbl)
        c = QLabel(chord_txt)
        c.setStyleSheet(
            f"color:{T.TEXT_PRIMARY if is_new_chord else T.TEXT_DIM};"
            f"font-family:'{T.FONT_SANS_EN}';font-size:16px;font-weight:700;border:none;")
        v.addWidget(c)
        s = QLabel(scale_txt)
        s.setStyleSheet(
            f"color:{T.BADGE_OUT if detour else T.TEXT_MUTED};"
            f"font-family:'{T.FONT_MONO}';font-size:10px;border:none;")
        v.addWidget(s)

        if seg is not None:        # 모든 마디 클릭 → 코드 수동 수정(§1)
            cell.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            cell.mousePressEvent = lambda e, sg=seg: self._edit_chord(sg)
        return cell

    # ── 수동 코드 수정 ───────────────────────────────────────────
    def _edit_chord(self, seg):
        names = [pc_name(r) + suf for r in range(12) for suf in _EDIT_SUFFIXES]
        cur = seg.chord.name
        start = names.index(cur) if cur in names else 0
        name, ok = QInputDialog.getItem(
            self, "코드 수정", f"이 마디(현재 {cur})의 코드를 고르세요:",
            names, start, False)
        if ok and name and name != cur:
            self._apply_chord(seg, name)

    def _apply_chord(self, seg, name: str):
        """수동 선택 코드로 구간의 코드·스케일·리프를 재계산."""
        chord = parse_chord(name)
        key_root = self.tl.key_root
        key_mode = "minor" if "minor" in (self.tl.key or "").lower() else "major"
        home = set(scale_pcs(key_root, key_mode))
        is_detour = not all(pc in home for pc in chord.chord_tones())
        note_set = (sorted(set(chord.chord_scale()) | set(chord.chord_tones()))
                    if is_detour else sorted(home))
        o = diatonic_option(chord, key_root, key_mode, is_detour, note_set)
        seg.chord = chord
        seg.candidates = [ScaleOption(o["kind"], o["root"], o["name"], o["note_set"])]
        seg.degree = degree_for(chord, key_root)
        seg.is_detour = is_detour
        bake_segment(self.tl, seg, self._model)   # 새 종류 리프 생성 + example 갱신
        self._build_riffs()
        self._build_grid()
