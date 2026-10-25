"""[4] 학습 설정 — 곡 전체 스케일 1개 + 연습 방식(자유 / 착지음).

- 스케일: 펜타토닉(추천) · 키 스케일 7음 · 블루스. 키 밖 코드(예외 구간)는 로컬 스케일 유지.
- 착지음 목표는 선택한 스케일로 곡의 모든 코드에서 가능한 것만 켠다.
- 음 개수(코드 하나에서 칠 스케일 음): 사용안함 / 정해진 개수 / 개수 범위.
"""
from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QSpinBox
)
from PyQt6.QtCore import pyqtSignal

from analyze.theory import song_scale_options, pc_name
from ml.generate import _landing_pc
from gui import theme as T
from gui.widgets.elided_label import ElidedLabel

GOALS = (("root", "1도"), ("third", "3도"), ("seventh", "7도"), ("chord_tone", "코드톤"))


def landing_blocker(tl, option: dict, goal: str) -> str | None:
    """option 스케일로 goal 착지가 불가능한 첫 코드의 이유, 모두 가능하면 None."""
    for seg in tl.segments:
        note_set = seg.note_set if seg.is_detour else option["note_set"]
        if _landing_pc(SimpleNamespace(chord=seg.chord, note_set=note_set), goal) is None:
            return f"{seg.chord.name} 코드의 {dict(GOALS)[goal]} 음이 스케일에 없어요"
    return None


def scale_fit(tl, option: dict) -> float:
    """키 안 구간의 코드톤이 스케일에 드는 비율(구간 길이 가중). 예외 구간은 로컬 스케일이라 제외."""
    total = hit = 0.0
    for seg in tl.segments:
        tones = seg.chord_tones()
        if seg.is_detour or not tones:
            continue
        total += seg.duration()
        hit += seg.duration() * len(set(tones) & set(option["note_set"])) / len(tones)
    return hit / total if total else 1.0


PENTA_MARGIN = 0.05   # 펜타토닉이 최고 적합도와 이만큼 이내면 쉬운 펜타를 추천


def recommend(tl, options: list[dict]) -> int | None:
    """사용 가능(모든 코드에 스케일 안 코드톤 1개 이상)한 후보 중 코드톤 포함률 최고. 펜타 근접 시 펜타."""
    usable = [i for i, o in enumerate(options) if landing_blocker(tl, o, "chord_tone") is None]
    if not usable:
        return None
    fits = {i: scale_fit(tl, options[i]) for i in usable}
    best = max(usable, key=fits.get)
    penta = next((i for i in usable if "펜타토닉" in options[i]["kind"]), None)
    return penta if penta is not None and fits[best] - fits[penta] <= PENTA_MARGIN else best


def chip_qss(selected: bool) -> str:
    if selected:
        return (f"QPushButton{{background:{T.WHITE};color:{T.BG_BASE};border:none;"
                f"border-radius:7px;padding:8px 14px;font-size:12px;font-weight:700;}}"
                f"QPushButton:focus{{border:1px solid {T.BORDER_ACTIVE};}}")
    return (f"QPushButton{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_BODY};"
            f"border:1px solid {T.BORDER_DEFAULT};border-radius:7px;padding:8px 14px;font-size:12px;}}"
            f"QPushButton:hover,QPushButton:focus{{border:1px solid {T.BORDER_ACTIVE};color:{T.TEXT_PRIMARY};}}"
            f"QPushButton:disabled{{color:{T.TEXT_DIM};border:1px solid {T.BORDER_SUBTLE};}}")


class SetupScreen(QWidget):
    practiceRequested = pyqtSignal()
    backToBeatRequested = pyqtSignal()
    chordEditRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl = None
        self._options: list[dict] = []
        self._scale = 0
        self._method = "free"
        self._goal = "third"
        content = T.compact_content(self)
        root = QVBoxLayout(content)
        root.setContentsMargins(T.PAD_H, T.PAD_V, T.PAD_H, T.PAD_V)
        root.setSpacing(12)

        top = QHBoxLayout()
        self.back_btn = QPushButton("← 박자 조정")
        self.back_btn.setStyleSheet(T.qss_ghost_btn())
        self.back_btn.clicked.connect(self.backToBeatRequested.emit)
        top.addWidget(self.back_btn)
        self.title = ElidedLabel("학습 설정")
        self.title.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-size:18px;font-weight:700;")
        top.addSpacing(8)
        top.addWidget(self.title, 1)
        self.key_lbl = QLabel("")
        self.key_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;")
        top.addWidget(self.key_lbl)
        self.chord_btn = QPushButton("코드 수정")
        self.chord_btn.setStyleSheet(T.qss_ghost_btn())
        self.chord_btn.setToolTip("코드·키·루프를 수정합니다. 확인하면 이 화면에 반영돼요.")
        self.chord_btn.clicked.connect(self.chordEditRequested.emit)
        top.addSpacing(8)
        top.addWidget(self.chord_btn)
        root.addLayout(top)

        root.addWidget(self._heading("스케일 — 곡 전체에 하나"))
        self.scale_row = QHBoxLayout()
        self.scale_btns: list[QPushButton] = []
        for i in range(3):
            btn = QPushButton()
            btn.clicked.connect(lambda _, k=i: self._pick_scale(k))
            self.scale_row.addWidget(btn)
            self.scale_btns.append(btn)
        self.scale_row.addStretch(1)
        root.addLayout(self.scale_row)
        self.scale_info = QLabel("")
        self.scale_info.setWordWrap(True)
        self.scale_info.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        root.addWidget(self.scale_info)

        root.addWidget(self._heading("연습 방식"))
        method_row = QHBoxLayout()
        self.method_btns = {}
        for key, text in (("free", "자유연습"), ("landing", "착지음")):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _, k=key: self._pick_method(k))
            method_row.addWidget(btn)
            self.method_btns[key] = btn
        method_row.addStretch(1)
        root.addLayout(method_row)

        # ── 착지음 옵션 ──
        self.landing_box = QWidget()
        lv = QVBoxLayout(self.landing_box)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        goal_row = QHBoxLayout()
        goal_row.addWidget(self._caption("코드가 바뀔 때 착지"))
        self.goal_btns = {}
        for key, text in GOALS:
            btn = QPushButton(text)
            btn.clicked.connect(lambda _, k=key: self._pick_goal(k))
            goal_row.addWidget(btn)
            self.goal_btns[key] = btn
        goal_row.addStretch(1)
        lv.addLayout(goal_row)
        count_row = QHBoxLayout()
        count_row.addWidget(self._caption("코드당 음 개수"))
        self.count_mode = QComboBox()
        self.count_mode.addItems(["사용안함", "정해진 개수", "개수 범위"])
        self.count_mode.setStyleSheet(T.qss_input())
        self.count_mode.currentIndexChanged.connect(self._sync_count)
        count_row.addWidget(self.count_mode)
        self.count_lo, self.count_hi = QSpinBox(), QSpinBox()
        for spin, value in ((self.count_lo, 3), (self.count_hi, 5)):
            spin.setRange(1, 8)
            spin.setValue(value)
            spin.setStyleSheet(T.qss_input())
            spin.valueChanged.connect(self._sync_count)
        self.count_dash = QLabel("~")
        self.count_dash.setStyleSheet(f"color:{T.TEXT_MUTED};")
        count_row.addWidget(self.count_lo)
        count_row.addWidget(self.count_dash)
        count_row.addWidget(self.count_hi)
        count_row.addStretch(1)
        lv.addLayout(count_row)
        root.addWidget(self.landing_box)
        root.addStretch(1)

        bottom = QHBoxLayout()
        note = QLabel("메인 화면의 '리프학습모드'에서 이 조건으로 리프를 만들어 연습할 수 있어요.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        bottom.addWidget(note, 1)
        self.go_btn = QPushButton("연습 시작 ▶")
        self.go_btn.setStyleSheet(T.qss_primary_btn())
        self.go_btn.clicked.connect(self._start)
        bottom.addWidget(self.go_btn)
        root.addLayout(bottom)

    @staticmethod
    def _heading(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_MONO}';font-size:13px;font-weight:700;")
        return lbl

    @staticmethod
    def _caption(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{T.TEXT_BODY};font-size:12px;")
        return lbl

    # ── 로드 ─────────────────────────────────────────────────────
    def set_timeline(self, tl):
        self.tl = tl
        mode = "minor" if "minor" in (tl.key or "").lower() else "major"
        self._options = song_scale_options(tl.key_root, mode)
        self.title.setText(tl.title or "학습 설정")
        self.key_lbl.setText(f"{tl.key}  ·  {tl.bpm:.0f} BPM")
        best = recommend(tl, self._options)
        for i, (btn, opt) in enumerate(zip(self.scale_btns, self._options)):
            reason = landing_blocker(tl, opt, "chord_tone")
            btn.setText(f"{opt['name']}  · 코드톤 {scale_fit(tl, opt):.0%}" + ("  · 추천" if i == best else ""))
            btn.setEnabled(reason is None)
            btn.setToolTip(reason.replace("코드톤 음이", "코드톤이 하나도") if reason else "")
        saved = tl.practice
        names = [o["name"] for o in self._options]
        name = saved.get("scale", {}).get("name")
        self._scale = (names.index(name) if name in names and self.scale_btns[names.index(name)].isEnabled()
                       else best if best is not None else 1)
        self._method = saved.get("method", "free")
        self._goal = saved.get("goal") or "third"
        count = saved.get("count")
        self.count_mode.setCurrentIndex(0 if not count else 1 if count[0] == count[1] else 2)
        if count:
            self.count_lo.setValue(count[0])
            self.count_hi.setValue(count[1])
        self._pick_scale(self._scale)
        self._pick_method(self._method)

    # ── 선택 ─────────────────────────────────────────────────────
    def _pick_scale(self, i: int):
        self._scale = i
        for k, btn in enumerate(self.scale_btns):
            btn.setStyleSheet(chip_qss(k == i))
        opt = self._options[i]
        detours = sum(seg.is_detour for seg in self.tl.segments)
        info = "음: " + " ".join(pc_name(opt["root"] + d) for d in sorted(
            (pc - opt["root"]) % 12 for pc in opt["note_set"]))
        if detours:
            info += f"  ·  예외 구간 {detours}개(키 밖 코드는 그 코드의 스케일 사용)"
        self.scale_info.setText(info)
        for key, btn in self.goal_btns.items():
            reason = landing_blocker(self.tl, opt, key)
            btn.setEnabled(reason is None)
            btn.setToolTip(reason or "")
        if not self.goal_btns[self._goal].isEnabled():
            self._goal = "chord_tone"     # 코드톤은 항상 가능(스케일 안 코드톤이 하나 이상)
        self._pick_goal(self._goal)

    def _pick_method(self, key: str):
        self._method = key
        for k, btn in self.method_btns.items():
            btn.setStyleSheet(chip_qss(k == key))
        self.landing_box.setVisible(key == "landing")

    def _pick_goal(self, key: str):
        self._goal = key
        for k, btn in self.goal_btns.items():
            btn.setStyleSheet(chip_qss(k == key))
        self._sync_count()

    def _sync_count(self, *_):
        mode = self.count_mode.currentIndex()
        self.count_lo.setVisible(mode > 0)
        self.count_hi.setVisible(mode == 2)
        self.count_dash.setVisible(mode == 2)
        if self.count_hi.value() < self.count_lo.value():
            self.count_hi.setValue(self.count_lo.value())

    def count(self):
        mode = self.count_mode.currentIndex()
        if mode == 0:
            return None
        lo = self.count_lo.value()
        return [lo, lo if mode == 1 else max(lo, self.count_hi.value())]

    def remember(self):
        """화면 선택을 tl.practice에 기록(스케일 적용 없이) — 새로고침해도 유지."""
        landing = self._method == "landing"
        self.tl.practice.update(scale=dict(self._options[self._scale]), method=self._method,
                                goal=self._goal if landing else None,
                                count=self.count() if landing else None)

    def _start(self):
        self.remember()
        self.tl.apply_song_scale(self._options[self._scale])
        self.practiceRequested.emit()
