"""[0] 링크 입력 화면 — ScaleRiff (디자인 스펙 §6 [0]).

- 워드마크 로고(원형 황동 링) + 'ScaleRiff' 세리프 워드마크
- 링크 붙여넣기 + 로컬 파일 선택
- (첫 실행) 온보딩 3카드. 스킵 가능
"""
from __future__ import annotations
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QFrame, QStackedWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize

from gui import theme as T
from gui.anim import stagger

try:
    from PyQt6.QtSvgWidgets import QSvgWidget
    _HAS_SVG = True
except Exception:
    _HAS_SVG = False

_LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "assets", "scaleriff_logo.svg")

ONBOARD_CARDS = [
    ("🔗  링크 넣기", "좋아하는 곡의 링크나 오디오 파일을 넣으면\n앱이 코드·키·박자를 분석해요."),
    ("🎼  스케일 가이드", "코드마다 어떤 스케일이 통하는지\n건반 색으로 알려줘요 — 코드톤·스케일음·밖."),
    ("🎹  직접 쳐보기", "곡 위에서 자유롭게 즉흥을 쳐봐요. 틀린 음은 없어요.\n연습 모드에선 AI 리프가 곡에 맞춰 흘러 따라 칠 수 있어요."),
]


def _logo_widget(size=72):
    if _HAS_SVG and os.path.exists(_LOGO):
        w = QSvgWidget(_LOGO)
        w.setFixedSize(QSize(size, size))
        return w
    lab = QLabel("◍")
    lab.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-size:{size}px;")
    return lab


class _Onboarding(QWidget):
    done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._idx = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.addStretch(1)

        self.card = QFrame()
        self.card.setStyleSheet(
            f"QFrame{{background:{T.BG_SURFACE};border:1px solid {T.BORDER_DEFAULT};"
            f"border-radius:16px;}}")
        self.card.setMinimumHeight(220)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(30, 30, 30, 30)
        self.title = QLabel()
        self.title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS}';"
            "font-size:22px;font-weight:700;border:none;")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body = QLabel()
        self.body.setStyleSheet(f"color:{T.TEXT_BODY};font-size:14px;border:none;")
        self.body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.setWordWrap(True)
        cl.addStretch(1); cl.addWidget(self.title); cl.addSpacing(14)
        cl.addWidget(self.body); cl.addStretch(1)
        lay.addWidget(self.card)

        lay.addSpacing(20)
        row = QHBoxLayout()
        self.next_btn = QPushButton("다음")
        self.next_btn.setStyleSheet(T.qss_primary_btn())
        self.next_btn.clicked.connect(self._next)
        row.addStretch(1); row.addWidget(self.next_btn); row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self._render()

    def _render(self):
        t, b = ONBOARD_CARDS[self._idx]
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
        self.stack = QStackedWidget(self)
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0)
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
        lay = QVBoxLayout(w)
        lay.setContentsMargins(80, 0, 80, 0)
        lay.setSpacing(6)
        lay.addStretch(1)

        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        logo = _logo_widget(56)
        logo_row.addWidget(logo)
        logo_row.addStretch(1)
        lay.addLayout(logo_row)

        title = QLabel("ScaleRiff")
        title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS_EN}';"
            "font-size:30px;font-weight:900;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        sub = QLabel("좋아하는 곡 위에서 배우는 즉흥 연주")
        sub.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:13px;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(sub)
        lay.addSpacing(12)

        side_btn_qss = (
            f"QPushButton{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_BODY};"
            f"border:1px solid {T.BORDER_DEFAULT};border-radius:10px;padding:10px 14px;}}"
            f"QPushButton:hover{{border:1px solid {T.BORDER_ACTIVE};}}")
        # 입력란들은 화면폭과 무관하게 고정폭 + 가운데 정렬(컴팩트)
        row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(
            "유튜브 링크, 오디오 파일, 또는 저장된 세션(.json) 경로를 붙여넣기")
        self.url_edit.setStyleSheet(T.qss_input())
        self.url_edit.returnPressed.connect(self._submit)
        row.addWidget(self.url_edit, 1)
        browse = QPushButton("파일선택")
        browse.setStyleSheet(side_btn_qss)
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        row_wrap = QWidget()
        row_wrap.setFixedWidth(520)
        row_wrap.setLayout(row)
        lay.addWidget(row_wrap, alignment=Qt.AlignmentFlag.AlignHCenter)

        # 분석 후 세션(.json) 저장 폴더
        save_row = QHBoxLayout()
        save_lbl = QLabel("분석 후 저장경로")
        save_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        save_row.addWidget(save_lbl)
        self.save_edit = QLineEdit()
        self.save_edit.setStyleSheet(
            f"QLineEdit{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_BODY};"
            f"border:1px solid {T.BORDER_DEFAULT};border-radius:8px;"
            "padding:6px 10px;font-size:12px;}")
        save_row.addWidget(self.save_edit, 1)
        save_btn = QPushButton("폴더선택")
        save_btn.setStyleSheet(side_btn_qss)
        save_btn.clicked.connect(self._browse_save_dir)
        save_row.addWidget(save_btn)
        save_wrap = QWidget()
        save_wrap.setFixedWidth(520)
        save_wrap.setLayout(save_row)
        lay.addWidget(save_wrap, alignment=Qt.AlignmentFlag.AlignHCenter)

        lay.addSpacing(10)
        # 버튼은 내용 크기 + 가운데 정렬(가로로 안 늘임)
        go_row = QHBoxLayout()
        go_row.addStretch(1)
        self.go_btn = QPushButton("분석 시작")
        self.go_btn.setStyleSheet(T.qss_primary_btn())
        self.go_btn.clicked.connect(self._submit)
        go_row.addWidget(self.go_btn)
        go_row.addStretch(1)
        lay.addLayout(go_row)
        lay.addStretch(2)
        # 입장 애니메이션 순서(위 → 아래)
        self._input_items = [logo, title, sub, row_wrap, save_wrap, self.go_btn]
        return w

    # ── 저장 폴더 ────────────────────────────────────────────────
    def save_dir(self) -> str:
        return self.save_edit.text().strip()

    def set_save_dir(self, d: str):
        self.save_edit.setText(d or "")

    def _browse_save_dir(self):
        d = QFileDialog.getExistingDirectory(self, "분석 후 저장 폴더 선택",
                                             self.save_dir() or "")
        if d:
            self.save_edit.setText(d)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "오디오/세션 파일 선택", "",
            "오디오/세션 (*.mp3 *.wav *.m4a *.flac *.ogg *.json);;"
            "저장된 세션 (*.json);;모든 파일 (*.*)")
        if path:
            self.url_edit.setText(path)

    def _submit(self):
        src = self.url_edit.text().strip()
        if src:
            self.buildRequested.emit(src)
