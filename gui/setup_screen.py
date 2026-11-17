"""[2] 학습 설정 — 곡 전체 스케일 1개만 고른다(연습은 자유연습으로 시작).

- 스케일: 펜타토닉(추천) · 키 스케일 7음 · 블루스. 키 밖 코드(예외 구간)는 로컬 스케일 유지.
- 착지음은 연주화면 리프모드의 리프 생성 창에서 체크한다.
"""
from __future__ import annotations

from types import SimpleNamespace

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QCheckBox, QScrollArea, QScroller,
)
from PyQt6.QtCore import Qt, pyqtSignal

from analyze.theory import song_scale_options
from ml.generate import _landing_pc
from gui import theme as T
from gui.anim import stagger

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


class SetupScreen(QWidget):
    practiceRequested = pyqtSignal()
    backToLinkRequested = pyqtSignal()
    settingsRequested = pyqtSignal()     # ⚙ — 연주화면과 같은 설정 창

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl = None
        self._options: list[dict] = []
        self._scale = 0
        self._skip = False                 # 키 밖 코드 제외(건반 강조·리프 없음)
        content = T.compact_content(self)
        # 창이 낮아도 잘리지 않게 스크롤 — 휠·스크롤바 외에 빈 곳을 끌어서도 움직인다
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)   # 창 공통 Backdrop이 비치게
        QScroller.grabGesture(scroll.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)
        page = QWidget()
        scroll.setWidget(page)
        page.setAutoFillBackground(False)               # setWidget이 켜는 채움을 끔
        wrap = QVBoxLayout(content)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addWidget(scroll)
        col = T.centered_column(page, 760)
        root = QVBoxLayout(col)
        root.setContentsMargins(T.PAD_H, T.PAD_V, T.PAD_H, T.PAD_V)
        root.setSpacing(16)

        # ── 모서리 [←] [⚙]: 연주화면과 같은 화면 좌표에 고정(resizeEvent) ──
        self.back_btn = QPushButton("←", self)
        self.back_btn.setToolTip("링크 입력으로")
        self.back_btn.clicked.connect(self.backToLinkRequested.emit)
        self.settings_btn = QPushButton("⚙", self)
        self.settings_btn.setAccessibleName("설정 — 박자·코드 조정, 입력·소리")
        self.settings_btn.clicked.connect(self.settingsRequested.emit)
        for b in (self.back_btn, self.settings_btn):
            b.setFixedSize(48, 48)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)   # 진입 시 Enter가 ←로 가지 않게(연주화면과 같음)
            b.setStyleSheet(T.qss_icon_btn())

        # ── 제목: 천장과 첫 카드의 중간. 카드·시작 버튼은 대략 세로 가운데(stretch 1:1:2) ──
        head = T.title_block("학습내용 선택", "")
        self.title = head.title
        root.addStretch(1)
        root.addWidget(head)
        self._boxes = [head]                   # 순차 등장 단위(위 → 아래)
        root.addStretch(1)

        # ── 곡 정보 카드: 곡 이름·추정 키 / 키 밖 코드 개수·제외 ──
        card, lay = self._card("곡 정보")
        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        self.song_lbl = QLabel("")
        self.song_lbl.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-size:15px;font-weight:700;")
        self.key_lbl = QLabel("")
        self.key_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:13px;")
        info_row.addWidget(self.song_lbl)
        info_row.addWidget(self.key_lbl)
        info_row.addStretch(1)
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
        self._boxes.append(card)

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
        self._boxes.append(card)
        root.addSpacing(4)

        self.go_btn = QPushButton("  연습 시작")
        self.go_btn.setIcon(T.icon("play.svg"))
        self.go_btn.setStyleSheet(T.qss_primary_btn() + "QPushButton{border-radius:23px;padding:0 32px;"
                                  "min-height:46px;font-size:15px;}")
        self.go_btn.clicked.connect(self._start)
        root.addWidget(self.go_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._boxes.append(self.go_btn)
        root.addStretch(2)

    def showEvent(self, e):
        super().showEvent(e)
        self.go_btn.setFocus()
        stagger(self._boxes)

    def keyPressEvent(self, e):
        """Enter = 연습 시작(포커스가 어디든 — 버튼들은 Enter를 받지 않고 여기로 올려보낸다)."""
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.go_btn.isEnabled():
            self.go_btn.click()
            return
        super().keyPressEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.back_btn.move(T.PAD_H + 8, 24)
        self.settings_btn.move(self.width() - T.PAD_H - 8 - 48, 24)
        self.back_btn.raise_()
        self.settings_btn.raise_()

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
        self._pick_scale(self._scale)

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

    def remember(self):
        """화면 선택을 tl.practice에 기록(스케일 적용 없이) — 새로고침해도 유지."""
        self.tl.practice.update(scale=dict(self._options[self._scale]), skip_detour=self._skip)

    def _start(self):
        self.remember()
        self.tl.apply_song_scale(self._options[self._scale])
        self.practiceRequested.emit()
