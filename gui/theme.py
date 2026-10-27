"""다크 스튜디오 디자인 토큰. 현행 기준: 이 파일."""
from __future__ import annotations
import os
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QFontDatabase, QPalette, QColor, QPainter, QLinearGradient, QRadialGradient, QPen, QIcon
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel

# ── §3.1 표면 / 배경 ─────────────────────────────────────────────
BG_BASE        = "#0d1421"
BG_SURFACE     = "#151e2e"
BG_SURFACE_ALT = "#1e283a"
BG_INSET       = "#0a0f19"
BORDER_SUBTLE  = "#232f44"
BORDER_DEFAULT = "#2e3c55"
ACCENT         = "#5b84ff"   # 남색 배경 위 포인트 파랑(주 버튼·포커스·선택)
ACCENT_LIGHT   = "#8b9cff"
BORDER_ACTIVE  = ACCENT
ACCENT_GRAD    = f"qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #4f7bff,stop:1 {ACCENT_LIGHT})"

# ── §3.2 텍스트 ──────────────────────────────────────────────────
TEXT_PRIMARY = "#f1f5f9"
TEXT_BODY    = "#d6dfe8"
TEXT_MUTED   = "#b2bfcc"
TEXT_DIM     = "#8e9bad"

# ── §3.3 배지 기능색 (키보드 위젯 전용) ─────────────────────────
BADGE_CHORD      = "#22c55e"   # 코드톤 배지 배경 — 초록
BADGE_ROOT       = "#3b82f6"   # 근음(1도) 배지 배경 — 파랑(코드톤 중 근음 구분)
BADGE_SCALE      = "#4a4a4a"   # 스케일음 배지 배경 — 짙은 회색
BADGE_OUT        = "#ef4444"   # 스케일 밖 배지 배경 — 빨강
DETOUR           = "#fdba74"   # 키 밖 코드(연주화면 코드 글자·박자선) — 옅은 주황
BADGE_TEXT       = "#ffffff"   # 모든 배지 텍스트 (코드톤·밖)
BADGE_SCALE_TEXT = "#e0e0e0"   # 스케일음 배지 텍스트

# ── §5.1 건반 고정 base color ────────────────────────────────────
KEY_W_FILL        = "#f2f2f2"  # 흰 건반 기본 fill
KEY_W_BORDER      = "#c8c8c8"  # 흰 건반 기본 border 1px
KEY_B_FILL        = "#1c1c1c"  # 검은 건반 기본 fill
KEY_WP_FILL       = "#eeeee8"  # 친 건반 흰 (미세 변화)
KEY_BP_FILL       = "#2a2a2a"  # 친 건반 검은 (미세 변화)

# ── §5.3 친 건반 상태 border ─────────────────────────────────────
KEY_PRESSED_CHORD = "#22c55e"  # 코드톤 친 건반 테두리
KEY_PRESSED_SCALE = "#888888"  # 스케일음 친 건반 테두리
KEY_SCALE_PRESSED_FILL = "#555555"  # UI 테두리색 변경과 독립적인 기존 눌림색
KEY_PRESSED_OUT   = "#ef4444"  # 스케일 밖 친 건반 테두리

# ── 공통 UI 엘리먼트 ─────────────────────────────────────────────
WHITE        = "#ffffff"
SCRUB_FILL   = "#7e92a9"
SCRUB_HEAD   = ACCENT_LIGHT
HOVER_OVERLAY = "rgba(255,255,255,0.08)"  # 버튼 hover 반투명 오버레이

# ── 하위 호환 별칭 ────────────────────────────────────────────────
TEXT_ACCENT = TEXT_MUTED
GOLD        = WHITE
GOLD_LIGHT  = TEXT_BODY
HEAD        = SCRUB_HEAD
GLOW        = WHITE
# v4 키보드 토큰 (piano.py가 더 이상 참조 안 함 — 외부 의존 방지용)
KEY_CHORD       = BADGE_CHORD
KEY_OUT         = BADGE_OUT

# ── §4 폰트 패밀리 ────────────────────────────────────────────────
FONT_SANS_EN = "Segoe UI"
FONT_MONO    = "Consolas"
FONT_SANS    = "Malgun Gothic"
FONT_SERIF    = FONT_SANS_EN   # 구 이름 별칭
FONT_SERIF_KR = FONT_SANS


def load_fonts():
    """assets/fonts/*.ttf|otf 번들 로드. 시스템 설치에 의존하지 않음(§4)."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "assets", "fonts")
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(d, fn))
    # Windows offscreen 플러그인은 시스템 폰트 목록을 자동으로 읽지 않는다.
    if os.name == "nt" and not QFontDatabase.families():
        fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        for name in ("malgun.ttf", "segoeui.ttf", "consola.ttf", "seguisym.ttf"):
            QFontDatabase.addApplicationFont(os.path.join(fonts, name))


# ── 공통 레이아웃 규칙 ───────────────────────────────────────────
# 모든 화면(새 화면 포함)의 기본 여백. root.setContentsMargins(PAD_H, PAD_V, PAD_H, PAD_V)
PAD_H = 28
PAD_V = 20
# 버튼 규칙: 텍스트보다 넓게 늘이지 말 것 — 내용 크기 + 좌우 stretch로 가운데 정렬.


def compact_content(parent: QWidget, max_width: int | None = None) -> QWidget:
    """편집/연주는 전체 영역, 준비 화면만 읽기 좋은 최대 폭을 사용한다."""
    palette = parent.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG_BASE))
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_BASE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(BG_SURFACE))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT_BODY))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT_BODY))
    parent.setPalette(palette)   # 배경은 칠하지 않음 — 창 공통 Backdrop이 비친다
    outer = QHBoxLayout(parent)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    content = QWidget(parent)
    content.setObjectName("compactContent")
    if max_width is not None:
        content.setMaximumWidth(max_width)
        outer.addStretch(1)
        outer.addWidget(content, 100)
        outer.addStretch(1)
    else:
        outer.addWidget(content)
    return content


class Backdrop(QWidget):
    """전 화면 공통 배경: 남색 세로 그라데이션 + 좌상·우하 모서리의 큰 원."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        g = QLinearGradient(0, 0, w * 0.3, h)
        g.setColorAt(0, QColor("#121b2c"))
        g.setColorAt(1, QColor(BG_BASE))
        p.fillRect(self.rect(), g)
        r = max(w, h) * 0.32
        for c in (QPointF(-r * 0.35, -r * 0.45), QPointF(w + r * 0.3, h + r * 0.25)):
            rg = QRadialGradient(c, r)
            rg.setColorAt(0.0, QColor(120, 150, 230, 4))
            rg.setColorAt(1.0, QColor(120, 150, 230, 15))
            p.setBrush(rg)
            p.setPen(QPen(QColor(140, 165, 255, 20), 1.2))
            p.drawEllipse(c, r, r)


def centered_column(parent: QWidget, max_width: int) -> QWidget:
    """parent 안에 최대 폭 max_width의 가운데 열을 만든다(링크 화면과 같은 읽기 폭)."""
    row = QHBoxLayout(parent)
    row.setContentsMargins(0, 0, 0, 0)
    col = QWidget(parent)
    col.setMaximumWidth(max_width)
    row.addStretch(1)
    row.addWidget(col, 100)
    row.addStretch(1)
    return col


def header_row(left: QWidget, title: QWidget, right: QWidget | None = None) -> QGridLayout:
    """좌·우 칸을 같은 비율로 늘려 제목이 정확히 가운데 오는 머리줄."""
    g = QGridLayout()
    g.setContentsMargins(0, 0, 0, 0)
    g.setColumnStretch(0, 1)
    g.setColumnStretch(2, 1)
    g.addWidget(left, 0, 0, Qt.AlignmentFlag.AlignLeft)
    g.addWidget(title, 0, 1)
    if right is not None:
        g.addWidget(right, 0, 2, Qt.AlignmentFlag.AlignRight)
    return g


def title_block(title: str, sub: QLabel | str) -> QWidget:
    """가운데 제목 + 보조 한 줄."""
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet(f"color:{TEXT_PRIMARY};font-size:20px;font-weight:700;")
    sub = sub if isinstance(sub, QLabel) else QLabel(sub)
    sub.setStyleSheet(f"color:{TEXT_MUTED};font-size:12px;")
    for lab in (t, sub):
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lab)
    w.title = t
    return w


def icon(name: str) -> QIcon:
    return QIcon(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "assets", "icons", name))


# ── 공통 QSS 스니펫 ──────────────────────────────────────────────
def qss_card(name: str, border: str = BORDER_DEFAULT) -> str:
    """objectName이 name인 QFrame 카드(링크 화면 입력 바·최근 분석과 같은 표면)."""
    return (f"QFrame#{name}{{background:{BG_SURFACE};border:1px solid {border};"
            "border-radius:16px;}")


def qss_section_title() -> str:
    return f"color:{TEXT_PRIMARY};font-size:15px;font-weight:700;"


def qss_primary_btn() -> str:
    return (
        f"QPushButton{{background:{ACCENT_GRAD};color:{WHITE};border:1px solid transparent;"
        "border-radius:19px;padding:10px 24px;min-height:18px;font-size:14px;font-weight:700;}"
        "QPushButton:hover{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #6b91ff,stop:1 #9eacff);}"
        f"QPushButton:pressed{{background:{ACCENT};}}"
        f"QPushButton:focus{{border:1px solid {WHITE};}}"
        f"QPushButton:disabled{{background:{BG_SURFACE_ALT};color:{TEXT_DIM};border-color:{BORDER_SUBTLE};}}"
    )


def qss_ghost_btn() -> str:
    return (
        f"QPushButton{{background:{BG_SURFACE_ALT};color:{TEXT_BODY};"
        f"border:1px solid {BORDER_DEFAULT};border-radius:10px;padding:7px 14px;min-height:18px;font-size:12px;}}"
        f"QPushButton:hover{{background:{BORDER_DEFAULT};color:{TEXT_PRIMARY};}}"
        f"QPushButton:pressed{{background:{BG_INSET};border-color:{BORDER_ACTIVE};}}"
        f"QPushButton:focus{{border-color:{BORDER_ACTIVE};}}"
        f"QPushButton:checked{{background:{ACCENT_GRAD};color:{WHITE};border-color:{ACCENT};}}"
        f"QPushButton:disabled{{background:{BG_INSET};color:{TEXT_DIM};border-color:{BORDER_SUBTLE};}}"
    )


def qss_icon_btn(color: str = TEXT_PRIMARY) -> str:
    """원형 아이콘 버튼(←, ⚙). 48×48 고정 크기와 함께 쓴다."""
    return (f"QPushButton{{background:{BG_SURFACE};color:{color};border:1px solid {BORDER_DEFAULT};"
            f"border-radius:23px;font-family:'Segoe UI Symbol';font-size:20px;padding:0 0 3px 0;"
            "min-width:44px;max-width:44px;min-height:44px;max-height:44px;}"
            f"QPushButton:hover{{background:{BG_SURFACE_ALT};border-color:{ACCENT};}}"
            f"QPushButton:focus{{border-color:{ACCENT};}}"
            f"QPushButton:pressed{{border-color:{ACCENT_LIGHT};color:{ACCENT_LIGHT};}}")


def qss_input() -> str:
    return (
        f"QLineEdit{{background:{BG_SURFACE};color:{TEXT_PRIMARY};"
        f"border:1px solid {BORDER_DEFAULT};border-radius:12px;padding:12px;font-size:14px;"
        f"selection-background-color:{BORDER_ACTIVE};selection-color:{BG_BASE};}}"
        f"QLineEdit:hover{{border-color:{TEXT_MUTED};}}"
        f"QLineEdit:focus{{border:1px solid {BORDER_ACTIVE};}}"
        f"QLineEdit:disabled{{color:{TEXT_DIM};background:{BG_INSET};}}"
    )


def qss_app() -> str:
    icons = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons")).replace("\\", "/")
    return (
        f"QMainWindow,QDialog{{background:{BG_BASE};color:{TEXT_BODY};}}"
        f"QWidget{{font-family:'{FONT_SANS}';font-size:13px;color:{TEXT_BODY};}}"
        "QLabel{background:transparent;border:none;}"
        + qss_ghost_btn() + qss_input() +
        f"QComboBox,QSpinBox{{background:{BG_SURFACE};color:{TEXT_BODY};border:1px solid {BORDER_DEFAULT};"
        "border-radius:7px;padding:6px 10px;min-height:18px;}"
        f"QComboBox:hover,QSpinBox:hover{{border-color:{TEXT_MUTED};}}"
        f"QComboBox:focus,QSpinBox:focus{{border-color:{BORDER_ACTIVE};}}"
        f"QComboBox:disabled,QSpinBox:disabled{{color:{TEXT_DIM};background:{BG_INSET};}}"
        f"QSpinBox::up-button,QSpinBox::down-button{{width:22px;background:{BG_SURFACE_ALT};border:none;}}"
        "QSpinBox::up-button{subcontrol-origin:border;subcontrol-position:top right;border-top-right-radius:6px;}"
        "QSpinBox::down-button{subcontrol-origin:border;subcontrol-position:bottom right;border-bottom-right-radius:6px;}"
        f"QSpinBox::up-button:hover,QSpinBox::down-button:hover{{background:{BORDER_DEFAULT};}}"
        f"QSpinBox::up-arrow{{image:url('{icons}/chevron-up.svg');width:10px;height:6px;}}"
        f"QSpinBox::down-arrow{{image:url('{icons}/chevron-down.svg');width:10px;height:6px;}}"
        f"QComboBox QAbstractItemView{{background:{BG_SURFACE};color:{TEXT_BODY};"
        f"selection-background-color:{BG_SURFACE_ALT};selection-color:{TEXT_PRIMARY};padding:6px;}}"
        f"QMenu{{background:{BG_SURFACE};border:1px solid {BORDER_DEFAULT};padding:6px;}}"
        "QMenu::item{padding:9px 22px;border-radius:4px;}"
        f"QMenu::item:selected{{background:{BG_SURFACE_ALT};}}"
        f"QToolTip{{background:{BG_SURFACE_ALT};color:{TEXT_PRIMARY};border:1px solid {BORDER_DEFAULT};padding:8px;}}"
        "QScrollArea{background:transparent;border:none;}"
        f"QScrollBar:vertical{{background:{BG_INSET};width:8px;border-radius:4px;margin:0;}}"
        f"QScrollBar::handle:vertical{{background:{BORDER_DEFAULT};border-radius:4px;min-height:28px;}}"
        f"QScrollBar::handle:vertical:hover{{background:{TEXT_DIM};}}"
        "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
        f"QScrollBar:horizontal{{background:{BG_INSET};height:8px;border-radius:4px;margin:0;}}"
        f"QScrollBar::handle:horizontal{{background:{BORDER_DEFAULT};border-radius:4px;min-width:28px;}}"
        f"QScrollBar::handle:horizontal:hover{{background:{TEXT_DIM};}}"
        "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}"
        "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:transparent;}"
        f"QSlider::groove:horizontal{{height:4px;background:{BORDER_DEFAULT};border-radius:2px;}}"
        f"QSlider::sub-page:horizontal{{background:{BORDER_ACTIVE};border-radius:2px;}}"
        f"QSlider::handle:horizontal{{background:{TEXT_PRIMARY};width:14px;margin:-5px 0;border-radius:7px;}}"
        f"QCheckBox::indicator{{width:16px;height:16px;border:1px solid {TEXT_DIM};border-radius:4px;}}"
        f"QCheckBox::indicator:checked{{background:{BORDER_ACTIVE};border-color:{BORDER_ACTIVE};}}"
        f"QStatusBar{{background:{BG_INSET};color:{TEXT_MUTED};font-size:11px;}}"
    )
