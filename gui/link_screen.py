"""[0] 링크 입력 화면 — ScaleRiff (디자인 스펙 §6 [0]).

- 워드마크 로고(원형 황동 링) + 'ScaleRiff' 세리프 워드마크
- 링크 붙여넣기 + 로컬 파일 선택
- 최근 저장경로를 링크 입력란 아래에 표시
- 최근 분석 세션 3개 — 클릭 즉시 로드
- 제한 모드(백그라운드 분석 중): 세션(.json) 선택만 활성
- (첫 실행) 온보딩 3카드. 스킵 가능
"""
from __future__ import annotations
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QFrame, QStackedWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import QIcon

from gui import theme as T
from gui.anim import stagger

try:
    from PyQt6.QtSvgWidgets import QSvgWidget
    _HAS_SVG = True
except Exception:
    _HAS_SVG = False

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
_LOGO = os.path.join(_ASSETS, "scaleriff_logo.svg")
_FORMATS = "YouTube 링크 · MP3, WAV, M4A, FLAC, OGG · 저장된 세션 JSON"

ONBOARD_CARDS = [
    ("좋아하는 곡에서 시작하세요", "링크나 오디오 파일을 넣으면 코드·키·박자를 분석해요.\n분석이 끝나면 박자와 코드를 직접 확인할 수 있어요."),
    ("다음 음을 미리 확인하세요", "파랑은 근음, 초록은 코드톤, 회색은 스케일음이에요.\n다음 코드의 안내는 건반 아래 작은 막대로 예고해요."),
    ("듣고, 따라 치고, 바꿔보세요", "짧은 리프를 따라 친 뒤 리듬과 끝음을 바꿔보세요.\n자유 즉흥에서는 스케일 밖 경과음을 일괄 오답 처리하지 않아요."),
]


def _logo_widget(size=72):
    if _HAS_SVG and os.path.exists(_LOGO):
        w = QSvgWidget(_LOGO)
        w.setFixedSize(QSize(size, size))
        return w
    lab = QLabel("◍")
    lab.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-size:{size}px;")
    return lab


def _icon(name):
    return os.path.join(_ASSETS, "icons", name)


def _icon_label(name, size):
    lab = QLabel()
    lab.setPixmap(QIcon(_icon(name)).pixmap(QSize(size, size)))
    return lab


class _Onboarding(QWidget):
    done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._idx = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 30, 30, 30)
        lay.addStretch(1)

        self.card = QFrame()
        self.card.setStyleSheet(
            f"QFrame{{background:{T.BG_SURFACE};border:1px solid {T.BORDER_DEFAULT};"
            f"border-radius:16px;}}")
        self.card.setMinimumHeight(165)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(22, 22, 22, 22)
        self.position = QLabel()
        self.position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.position.setStyleSheet(f"color:{T.BORDER_ACTIVE};font-size:12px;border:none;")
        cl.addWidget(self.position)
        self.title = QLabel()
        self.title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS}';"
            "font-size:22px;font-weight:700;border:none;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body = QLabel()
        self.body.setStyleSheet(f"color:{T.TEXT_BODY};font-size:14px;border:none;")
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setWordWrap(True)
        cl.addStretch(1); cl.addWidget(self.title); cl.addSpacing(11)
        cl.addWidget(self.body); cl.addStretch(1)
        lay.addWidget(self.card)

        lay.addSpacing(15)
        row = QHBoxLayout()
        self.next_btn = QPushButton("다음")
        self.next_btn.setStyleSheet(T.qss_primary_btn())
        self.next_btn.clicked.connect(self._next)
        skip = QPushButton("건너뛰기")
        skip.setStyleSheet(T.qss_ghost_btn())
        skip.clicked.connect(self.done.emit)
        row.addStretch(1); row.addWidget(skip); row.addWidget(self.next_btn); row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self._render()

    def _render(self):
        t, b = ONBOARD_CARDS[self._idx]
        self.position.setText(f"{self._idx + 1} / {len(ONBOARD_CARDS)}")
        self.title.setText(t); self.body.setText(b)
        self.next_btn.setText("시작하기" if self._idx == len(ONBOARD_CARDS) - 1 else "다음")

    def _next(self):
        if self._idx >= len(ONBOARD_CARDS) - 1:
            self.done.emit()
        else:
            self._idx += 1
            self._render()


class LinkScreen(QWidget):
    buildRequested = pyqtSignal(str)   # source ("" = 데모)

    def __init__(self, show_onboarding=True, parent=None):
        super().__init__(parent)
        content = T.compact_content(self, max_width=860)
        self.stack = QStackedWidget(content)
        root = QVBoxLayout(content); root.setContentsMargins(T.PAD_H, T.PAD_V, T.PAD_H, T.PAD_V)
        root.addWidget(self.stack)

        self._onboard = _Onboarding()
        self._onboard.done.connect(lambda: self.stack.setCurrentIndex(1))
        self._input = self._build_input()
        self.stack.addWidget(self._onboard)   # 0
        self.stack.addWidget(self._input)     # 1
        self.stack.setCurrentIndex(0 if show_onboarding else 1)
        self.stack.currentChanged.connect(lambda _: self._animate_page())

    # ── 입장 애니메이션: 로고 → 제목 → 입력란 순 ────────────────
    def showEvent(self, e):
        super().showEvent(e)
        self._animate_page()

    def _animate_page(self):
        if self.stack.currentIndex() == 0:
            stagger([self._onboard.card, self._onboard.next_btn])
        else:
            stagger(self._input_items)

    def _build_input(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(18, 0, 18, 0)

        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addStretch(1)

        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        logo = _logo_widget(68)
        logo_row.addWidget(logo)
        logo_row.addStretch(1)
        lay.addLayout(logo_row)
        lay.addSpacing(6)

        title = QLabel(f"Scale<span style='color:{T.ACCENT_LIGHT}'>Riff</span>")
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS_EN}';"
            "font-size:44px;font-weight:700;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        sub = QLabel("좋아하는 곡 위에서 배우는 즉흥 연주")
        sub.setStyleSheet(f"color:{T.TEXT_BODY};font-size:14px;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(28)

        # 입력 바: 아이콘 · 입력란 | 파일 선택 · 분석 시작 을 한 상자에
        self._bar = QFrame()
        self._bar.setObjectName("inputBar")
        self._bar.setStyleSheet(
            f"QFrame#inputBar{{background:{T.BG_SURFACE};border:1px solid {T.BORDER_DEFAULT};"
            "border-radius:16px;}"
            f"QFrame#inputBar[focus=\"true\"]{{border-color:{T.ACCENT};}}"
            f"QFrame#barDivider{{background:{T.BORDER_DEFAULT};border:none;}}")
        row = QHBoxLayout(self._bar)
        row.setContentsMargins(18, 6, 6, 6)
        row.setSpacing(10)
        row.addWidget(_icon_label("music.svg", 20))
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("곡 링크 또는 오디오·세션 파일 경로")
        self.url_edit.setAccessibleName("곡 링크 또는 파일 경로")
        self.url_edit.setStyleSheet(
            f"QLineEdit{{background:transparent;border:none;color:{T.TEXT_PRIMARY};"
            f"font-size:15px;padding:10px 4px;selection-background-color:{T.ACCENT};}}"
            f"QLineEdit:disabled{{color:{T.TEXT_DIM};}}")
        self.url_edit.returnPressed.connect(self._submit)
        self.url_edit.installEventFilter(self)
        row.addWidget(self.url_edit, 1)
        divider = QFrame()
        divider.setObjectName("barDivider")
        divider.setFixedWidth(1)
        row.addWidget(divider)
        browse = QPushButton("  파일 선택")
        browse.setIcon(QIcon(_icon("folder.svg")))
        browse.setIconSize(QSize(18, 18))
        browse.setStyleSheet(T.qss_ghost_btn() + "QPushButton{border:none;border-radius:20px;min-height:40px;"
                             "font-size:13px;padding:0 18px;}")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        self.go_btn = QPushButton("  분석 시작")
        self.go_btn.setIcon(QIcon(_icon("play.svg")))
        self.go_btn.setIconSize(QSize(14, 14))
        self.go_btn.setStyleSheet(T.qss_primary_btn() + "QPushButton{border-radius:22px;padding:0 26px;min-height:42px;}")
        self.go_btn.clicked.connect(self._submit)
        row.addWidget(self.go_btn)
        row_wrap = self._bar
        lay.addWidget(row_wrap)
        lay.addSpacing(12)

        self._save_dir = ""
        self.save_label = QLabel()
        self.save_label.setWordWrap(True)
        self.save_label.setTextFormat(Qt.TextFormat.PlainText)
        self.save_label.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:13px;padding-left:4px;")
        lay.addWidget(self.save_label)
        self.input_hint = QLabel(_FORMATS)   # 빈 입력 시 안내로 바뀜
        self.input_hint.setWordWrap(True)
        self.input_hint.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:13px;padding-left:4px;")
        lay.addWidget(self.input_hint)

        # 최근 분석 세션(최대 3) — 클릭 즉시 로드
        self.recent_box = QWidget()
        self._recent_lay = QVBoxLayout(self.recent_box)
        self._recent_lay.setContentsMargins(0, 22, 0, 0)
        self._recent_lay.setSpacing(8)
        lay.addWidget(self.recent_box)
        self.recent_box.hide()

        lay.addStretch(1)
        outer.addWidget(col)

        # 제한 모드에서 잠글 위젯들(세션 선택만 남김)
        self._restricted_widgets = (self.url_edit, self.go_btn)
        self._restricted = False
        # 입장 애니메이션 순서(위 → 아래)
        self._input_items = [logo, title, sub, row_wrap, self.save_label]
        return w

    # ── 제한 모드(백그라운드 분석 중) — 세션(.json) 선택만 활성 ──
    def set_restricted(self, on: bool):
        self._restricted = bool(on)
        for wdg in self._restricted_widgets:
            wdg.setEnabled(not on)

    # ── 저장 폴더 ────────────────────────────────────────────────
    def save_dir(self) -> str:
        return self._save_dir

    def set_save_dir(self, d: str):
        self._save_dir = (d or "").strip()
        self.save_label.setText(f"최근 저장경로: {self._save_dir}")
        self.save_label.setToolTip(self._save_dir)

    def set_recent(self, paths):
        while self._recent_lay.count():
            self._recent_lay.takeAt(0).widget().deleteLater()
        paths = [p for p in paths if os.path.isfile(p)][:3]
        if paths:
            head = QLabel("최근 분석")
            head.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-size:14px;font-weight:700;padding-left:4px;")
            self._recent_lay.addWidget(head)
        for p in paths:
            # 세션 파일명 = "{제목}_{해시16}.json"
            name = os.path.splitext(os.path.basename(p))[0].rsplit("_", 1)[0]
            btn = QPushButton()
            btn.setAccessibleName(name or os.path.basename(p))
            btn.setToolTip(p)
            btn.setStyleSheet(
                f"QPushButton{{background:{T.BG_SURFACE};border:1px solid {T.BORDER_DEFAULT};border-radius:14px;min-height:52px;}}"
                f"QPushButton:hover{{background:{T.BG_SURFACE_ALT};}}"
                f"QPushButton:focus{{border-color:{T.ACCENT};}}")
            bl = QHBoxLayout(btn)
            bl.setContentsMargins(22, 0, 22, 0)
            bl.setSpacing(14)
            text = QLabel(btn.accessibleName())
            text.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-size:14px;")
            for part in (_icon_label("clock.svg", 20), text, _icon_label("arrow-right.svg", 18)):
                part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                bl.addWidget(part, 1 if part is text else 0)
            btn.clicked.connect(lambda _, p=p: self.buildRequested.emit(p))
            self._recent_lay.addWidget(btn)
        self.recent_box.setVisible(bool(paths))

    def _browse(self):
        if self._restricted:    # 분석 중 — 세션 열기만, 선택 즉시 로드
            path, _ = QFileDialog.getOpenFileName(
                self, "저장된 세션 선택", self.save_dir() or "",
                "저장된 세션 (*.json)")
            if path:
                self.buildRequested.emit(path)
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "오디오/세션 파일 선택", "",
            "오디오/세션 (*.mp3 *.wav *.m4a *.flac *.ogg *.json);;"
            "저장된 세션 (*.json);;모든 파일 (*.*)")
        if path:
            self.url_edit.setText(path)

    def eventFilter(self, obj, e):
        if obj is self.url_edit and e.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._bar.setProperty("focus", e.type() == QEvent.Type.FocusIn)
            self._bar.style().polish(self._bar)
        return super().eventFilter(obj, e)

    def _submit(self):
        if self._restricted:
            return
        src = self.url_edit.text().strip()
        if src:
            self.buildRequested.emit(src)
        else:
            self.input_hint.setText("곡 링크나 파일 경로를 입력하거나 ‘파일 선택’을 눌러주세요.")
            self.url_edit.setFocus()
