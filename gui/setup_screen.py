"""[4] 학습 설정 — 곡 전체 스케일 1개 + 연습 방식(자유 / 착지음).

- 스케일: 펜타토닉(추천) · 키 스케일 7음 · 블루스. 키 밖 코드(예외 구간)는 로컬 스케일 유지.
- 착지음 목표는 선택한 스케일로 곡의 모든 코드에서 가능한 것만 켠다.
- 음 개수(리프 하나에서 칠 스케일 음, 최소 3): 사용안함 / 정해진 개수 / 개수 범위.
"""
from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QComboBox, QSpinBox,
    QFrame, QGraphicsOpacityEffect, QCheckBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from analyze.theory import song_scale_options
from ml.generate import _landing_pc
from gui import theme as T

GOALS = (("root", "1도"), ("third", "3도"), ("seventh", "7도"), ("chord_tone", "코드톤"))

# 스케일 종류별 (느낌, 쓰임) 안내 — song_scale_options의 kind 기준
SCALE_GUIDE = {
    "메이저 펜타토닉": ("밝고 시원해요. 5음뿐이라 부딪히는 음이 거의 없어요.",
                    "팝·컨트리·록 멜로디, 즉흥 입문"),
    "마이너 펜타토닉": ("어둡고 힘 있는 소리. 록·블루스 기타 솔로의 기본이에요.",
                    "록·블루스·R&B 솔로, 즉흥 입문"),
    "메이저": ("밝고 안정적인 7음. 곡의 멜로디를 그대로 담아요.",
             "멜로디 따라 치기, 코드톤 착지 연습 — 4·7도는 코드에 따라 부딪힐 수 있어요"),
    "마이너": ("슬프고 서정적인 7음(자연단음계).",
             "발라드·단조 곡 멜로디 — 2·6도는 코드에 따라 부딪힐 수 있어요"),
    "블루스": ("마이너 펜타토닉 + ♭5 블루노트. 끈적하고 거친 느낌이에요.",
             "블루스·록·펑크 솔로 — 블루노트는 오래 끌지 말고 지나가는 음으로"),
}


def landing_blocker(tl, option: dict, goal: str, skip_detour=False) -> str | None:
    """option 스케일로 goal 착지가 불가능한 첫 코드의 이유, 모두 가능하면 None. 제외한 키 밖 코드는 안 본다."""
    for seg in tl.segments:
        if skip_detour and seg.is_detour:
            continue
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


def recommend(tl, options: list[dict], skip_detour=False) -> int | None:
    """사용 가능(모든 코드에 스케일 안 코드톤 1개 이상)한 후보 중 코드톤 포함률 최고. 펜타 근접 시 펜타."""
    usable = [i for i, o in enumerate(options) if landing_blocker(tl, o, "chord_tone", skip_detour) is None]
    if not usable:
        return None
    fits = {i: scale_fit(tl, options[i]) for i in usable}
    best = max(usable, key=fits.get)
    penta = next((i for i in usable if "펜타토닉" in options[i]["kind"]), None)
    return penta if penta is not None and fits[best] - fits[penta] <= PENTA_MARGIN else best


def chip_qss(selected: bool) -> str:
    """곡 스케일 칩(같은 폭 3칸)."""
    base = "border-radius:12px;padding:0 14px;min-height:44px;font-size:14px;"
    if selected:
        return (f"QPushButton{{background:{T.ACCENT_GRAD};color:{T.WHITE};border:1px solid {T.ACCENT};"
                f"{base}font-weight:700;}}"
                f"QPushButton:focus{{border:1px solid {T.WHITE};}}")
    return (f"QPushButton{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_BODY};"
            f"border:1px solid {T.BORDER_DEFAULT};{base}}}"
            f"QPushButton:hover,QPushButton:focus{{border:1px solid {T.ACCENT};color:{T.TEXT_PRIMARY};}}"
            f"QPushButton:disabled{{color:{T.TEXT_DIM};border:1px solid {T.BORDER_SUBTLE};}}")


def segment_qss(selected: bool) -> str:
    """착지 목표 세그먼트 버튼(어두운 홈 안)."""
    base = "border:none;border-radius:9px;padding:0 14px;min-width:36px;min-height:34px;font-size:13px;"
    if selected:
        return (f"QPushButton{{background:{T.ACCENT_GRAD};color:{T.WHITE};{base}font-weight:700;}}"
                f"QPushButton:disabled{{background:transparent;color:{T.TEXT_DIM};}}")
    return (f"QPushButton{{background:transparent;color:{T.TEXT_BODY};{base}}}"
            f"QPushButton:hover{{background:{T.BG_SURFACE_ALT};}}"
            "QPushButton:disabled{color:#5d6a7e;}")


def method_qss(selected: bool) -> str:
    """연습 방식 선택 카드(라디오 + 제목 + 설명)."""
    look = (f"background:rgba(91,132,255,0.14);border:1px solid {T.ACCENT};" if selected
            else f"background:{T.BG_SURFACE_ALT};border:1px solid {T.BORDER_DEFAULT};")
    return (f"QPushButton{{{look}border-radius:14px;min-height:60px;text-align:left;}}"
            f"QPushButton:hover,QPushButton:focus{{border-color:{T.ACCENT};}}")


def radio_qss(selected: bool) -> str:
    return (f"background:{T.WHITE};border:5px solid {T.ACCENT};border-radius:9px;" if selected
            else f"background:transparent;border:2px solid {T.TEXT_DIM};border-radius:9px;")


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
        self._skip = False                 # 키 밖 코드 제외(건반 강조·리프 없음)
        content = T.compact_content(self)
        col = T.centered_column(content, 760)
        root = QVBoxLayout(col)
        root.setContentsMargins(T.PAD_H, T.PAD_V, T.PAD_H, T.PAD_V)
        root.setSpacing(16)

        # ── 머리줄: ← · 제목 ──────────────────────────────────────
        self.back_btn = QPushButton("←")
        self.back_btn.setToolTip("박자 조정으로")
        self.back_btn.setFixedSize(48, 48)
        self.back_btn.setStyleSheet(T.qss_icon_btn())
        self.back_btn.clicked.connect(self.backToBeatRequested.emit)
        head = T.title_block("학습내용 선택", "")
        self.title = head.title
        root.addLayout(T.header_row(self.back_btn, head))
        root.addSpacing(4)

        # ── 곡 정보 카드: 곡 이름·추정 키·코드 수정 / 키 밖 코드 개수·제외 ──
        card, lay = self._card("곡 정보")
        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        self.song_lbl = QLabel("")
        self.song_lbl.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-size:15px;font-weight:700;")
        self.key_lbl = QLabel("")
        self.key_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:13px;")
        self.chord_btn = QPushButton("코드 수정")
        self.chord_btn.setStyleSheet(T.qss_ghost_btn() + "QPushButton{border-radius:19px;padding:0 16px;"
                                     "min-height:38px;font-size:13px;}")
        self.chord_btn.setToolTip("코드·키를 수정합니다. 확인하면 이 화면에 반영돼요.")
        self.chord_btn.clicked.connect(self.chordEditRequested.emit)
        info_row.addWidget(self.song_lbl)
        info_row.addWidget(self.key_lbl)
        info_row.addStretch(1)
        info_row.addWidget(self.chord_btn)
        lay.addLayout(info_row)
        self.detour_lbl = QLabel("")
        self.detour_lbl.setWordWrap(True)
        self.detour_lbl.setStyleSheet(f"color:{T.TEXT_BODY};font-size:13px;")
        lay.addWidget(self.detour_lbl)
        self.skip_chk = QCheckBox("키 밖 코드 제외 — 그 코드에선 건반 강조와 리프를 끕니다")
        self.skip_chk.setStyleSheet(f"color:{T.TEXT_BODY};font-size:13px;")
        self.skip_chk.clicked.connect(self._pick_skip)   # 사용자 클릭만(set_timeline의 setChecked는 무시)
        lay.addWidget(self.skip_chk)
        root.addWidget(card)

        # ── 곡 스케일 카드 ────────────────────────────────────────
        card, lay = self._card("곡 스케일")
        scale_row = QHBoxLayout()
        scale_row.setSpacing(10)
        self.scale_btns: list[QPushButton] = []
        self.rec_lbls: list[QLabel] = []         # 칩 오른쪽 안 '추천' 배지(추천 칩만 글자)
        for i in range(3):
            btn = QPushButton()
            btn.clicked.connect(lambda _, k=i: self._pick_scale(k))
            inner = QHBoxLayout(btn)
            inner.setContentsMargins(0, 0, 10, 0)
            inner.addStretch(1)
            rec = QLabel("")
            rec.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            rec.setStyleSheet(f"color:{T.WHITE};background:rgba(255,255,255,0.18);border-radius:7px;"
                              "padding:1px 8px;font-size:11px;font-weight:700;")
            inner.addWidget(rec, 0, Qt.AlignmentFlag.AlignVCenter)
            scale_row.addWidget(btn, 1)
            self.scale_btns.append(btn)
            self.rec_lbls.append(rec)
        lay.addLayout(scale_row)
        guide = QFrame()
        guide.setObjectName("guideBox")
        guide.setStyleSheet(f"QFrame#guideBox{{background:{T.BG_INSET};border-radius:12px;}}")
        g = QGridLayout(guide)
        g.setContentsMargins(16, 12, 16, 12)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(6)
        g.setColumnStretch(1, 1)
        self.feel_lbl, self.use_lbl = QLabel(""), QLabel("")
        for r, (name, lbl) in enumerate((("느낌", self.feel_lbl), ("쓰임", self.use_lbl))):
            tag = QLabel(name)
            tag.setStyleSheet(f"color:{T.TEXT_DIM};font-size:12px;")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color:{T.TEXT_BODY};font-size:12px;")
            g.addWidget(tag, r, 0, Qt.AlignmentFlag.AlignTop)
            g.addWidget(lbl, r, 1)
        lay.addWidget(guide)
        root.addWidget(card)

        # ── 연습 방식 카드: 자유연습 | 착지음 + 착지음 설정 ────────
        card, lay = self._card("연습 방식")
        method_row = QHBoxLayout()
        method_row.setSpacing(10)
        self.method_btns = {}
        self._radios = {}
        for key, text, desc in (("free", "자유연습", "스케일 안에서 자유롭게 즉흥해요"),
                                ("landing", "착지음", "코드가 바뀔 때 목표음에 도착해요")):
            btn = QPushButton()
            btn.setAccessibleName(text)
            btn.clicked.connect(lambda _, k=key: self._pick_method(k))
            inner = QHBoxLayout(btn)
            inner.setContentsMargins(18, 10, 18, 10)
            inner.setSpacing(14)
            radio = QLabel()
            radio.setFixedSize(18, 18)
            words = QVBoxLayout()
            words.setSpacing(2)
            name = QLabel(text)
            name.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-size:14px;font-weight:700;")
            sub = QLabel(desc)
            sub.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
            words.addWidget(name)
            words.addWidget(sub)
            for w in (radio, name, sub):
                w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            inner.addWidget(radio)
            inner.addLayout(words, 1)
            method_row.addWidget(btn, 1)
            self.method_btns[key] = btn
            self._radios[key] = radio
        lay.addLayout(method_row)

        # 착지음 설정 — 항상 보이고, 착지음일 때만 활성(아니면 흐리게)
        self.landing_box = QFrame()
        self.landing_box.setObjectName("landingBox")
        lv = QVBoxLayout(self.landing_box)
        lv.setContentsMargins(18, 12, 18, 14)
        lv.setSpacing(10)
        top = QHBoxLayout()
        sub_title = QLabel("착지음 설정")
        sub_title.setStyleSheet(f"color:{T.TEXT_BODY};font-size:13px;font-weight:700;")
        self.landing_hint = QLabel("착지음을 고르면 설정할 수 있어요")
        self.landing_hint.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        top.addWidget(sub_title)
        top.addStretch(1)
        top.addWidget(self.landing_hint)
        lv.addLayout(top)
        form = QGridLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setColumnMinimumWidth(0, 110)
        form.setColumnStretch(2, 1)
        form.addWidget(self._caption("착지 목표"), 0, 0)
        segment = QFrame()
        segment.setObjectName("segment")
        segment.setStyleSheet(f"QFrame#segment{{background:{T.BG_INSET};border:1px solid {T.BORDER_SUBTLE};"
                              "border-radius:12px;}")
        seg = QHBoxLayout(segment)
        seg.setContentsMargins(4, 4, 4, 4)
        seg.setSpacing(4)
        self.goal_btns = {}
        for key, text in GOALS:
            btn = QPushButton(text)
            btn.clicked.connect(lambda _, k=key: self._pick_goal(k))
            seg.addWidget(btn)
            self.goal_btns[key] = btn
        form.addWidget(segment, 0, 1)
        form.addWidget(self._caption("리프당 음 개수"), 1, 0)
        count_row = QHBoxLayout()
        count_row.setSpacing(8)
        self.count_mode = QComboBox()
        self.count_mode.addItems(["사용안함", "정해진 개수", "개수 범위"])
        self.count_mode.setMinimumWidth(150)
        self.count_mode.currentIndexChanged.connect(self._sync_count)
        count_row.addWidget(self.count_mode)
        self.count_lo, self.count_hi = QSpinBox(), QSpinBox()
        for spin, value in ((self.count_lo, 3), (self.count_hi, 5)):
            spin.setRange(3, 8)
            spin.setValue(value)
            spin.valueChanged.connect(self._sync_count)
        self.count_dash = QLabel("~")
        self.count_dash.setStyleSheet(f"color:{T.TEXT_MUTED};")
        count_row.addWidget(self.count_lo)
        count_row.addWidget(self.count_dash)
        count_row.addWidget(self.count_hi)
        count_row.addStretch(1)
        form.addLayout(count_row, 1, 1, 1, 2)
        lv.addLayout(form)
        lay.addWidget(self.landing_box)
        root.addWidget(card)
        root.addSpacing(4)

        self.go_btn = QPushButton("  연습 시작")
        self.go_btn.setIcon(T.icon("play.svg"))
        self.go_btn.setStyleSheet(T.qss_primary_btn() + "QPushButton{border-radius:23px;padding:0 32px;"
                                  "min-height:46px;font-size:15px;}")
        self.go_btn.clicked.connect(self._start)
        root.addWidget(self.go_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        root.addStretch(1)

    @staticmethod
    def _card(title):
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(T.qss_card("card"))
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 20)
        lay.setSpacing(12)
        head = QLabel(title)
        head.setStyleSheet(T.qss_section_title())
        lay.addWidget(head)
        return card, lay

    @staticmethod
    def _caption(text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:13px;")
        return lbl

    # ── 로드 ─────────────────────────────────────────────────────
    def set_timeline(self, tl):
        self.tl = tl
        mode = "minor" if "minor" in (tl.key or "").lower() else "major"
        self._options = song_scale_options(tl.key_root, mode)
        self.song_lbl.setText(tl.title or tl.audio_ref or "내 곡")
        self.key_lbl.setText(f"추정 키: {tl.key}")
        detours = [s.chord.name for s in tl.segments if s.is_detour]
        kinds = list(dict.fromkeys(detours))
        self.detour_lbl.setText(f"키 밖 코드 {len(kinds)}종 · {len(detours)}번 나와요 ({', '.join(kinds)})"
                                if detours else "키 밖 코드가 없어요")
        self._skip = bool(detours and tl.practice.get("skip_detour"))
        self.skip_chk.setChecked(self._skip)
        self.skip_chk.setEnabled(bool(detours))
        best = self._sync_scales()
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

    def _sync_scales(self):
        """스케일 칩 사용 가능·추천 표시 → 추천 번호. 키 밖 코드 제외 여부에 따라 달라진다."""
        best = recommend(self.tl, self._options, self._skip)
        for i, (btn, opt) in enumerate(zip(self.scale_btns, self._options)):
            reason = landing_blocker(self.tl, opt, "chord_tone", self._skip)
            btn.setText(opt["name"])
            self.rec_lbls[i].setText("추천" if i == best else "")
            self.rec_lbls[i].setVisible(i == best)
            btn.setEnabled(reason is None)
            btn.setToolTip(reason.replace("코드톤 음이", "코드톤이 하나도") if reason else "")
        return best

    # ── 선택 ─────────────────────────────────────────────────────
    def _pick_skip(self, on: bool):
        self._skip = on
        best = self._sync_scales()
        if not self.scale_btns[self._scale].isEnabled():
            self._scale = best if best is not None else 1
        self._pick_scale(self._scale)

    def _pick_scale(self, i: int):
        self._scale = i
        for k, btn in enumerate(self.scale_btns):
            btn.setStyleSheet(chip_qss(k == i))
        opt = self._options[i]
        feel, use = SCALE_GUIDE.get(opt["kind"], ("", ""))
        self.feel_lbl.setText(feel)
        self.use_lbl.setText(use)
        for key, btn in self.goal_btns.items():
            reason = landing_blocker(self.tl, opt, key, self._skip)
            btn.setEnabled(reason is None)
            btn.setToolTip(reason or "")
        if not self.goal_btns[self._goal].isEnabled():
            self._goal = "chord_tone"     # 코드톤은 항상 가능(스케일 안 코드톤이 하나 이상)
        self._pick_goal(self._goal)

    def _pick_method(self, key: str):
        self._method = key
        for k, btn in self.method_btns.items():
            btn.setStyleSheet(method_qss(k == key))
            self._radios[k].setStyleSheet(radio_qss(k == key))
        on = key == "landing"
        self.landing_box.setEnabled(on)   # 세부 옵션은 항상 보이고, 착지음일 때만 활성(아니면 흐리게)
        self.landing_hint.setVisible(not on)
        self.landing_box.setStyleSheet(
            f"QFrame#landingBox{{border-radius:14px;"
            + ("background:rgba(91,132,255,0.05);border:1px solid #34466a;}" if on
               else f"background:transparent;border:1px dashed {T.BORDER_DEFAULT};}}"))
        effect = None
        if not on:
            effect = QGraphicsOpacityEffect(self.landing_box)
            effect.setOpacity(0.42)
        self.landing_box.setGraphicsEffect(effect)

    def _pick_goal(self, key: str):
        self._goal = key
        for k, btn in self.goal_btns.items():
            btn.setStyleSheet(segment_qss(k == key))
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
                                count=self.count() if landing else None, skip_detour=self._skip)

    def _start(self):
        self.remember()
        self.tl.apply_song_scale(self._options[self._scale])
        self.practiceRequested.emit()
