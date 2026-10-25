"""다크 스튜디오 디자인 토큰. 현행 기준: 이 파일."""
from __future__ import annotations
import os
from PyQt6.QtGui import QFontDatabase, QPalette, QColor
from PyQt6.QtWidgets import QWidget, QHBoxLayout

# ── §3.1 표면 / 배경 ─────────────────────────────────────────────
BG_BASE        = "#11161d"
BG_SURFACE     = "#1a222c"
BG_SURFACE_ALT = "#242f3d"
BG_INSET       = "#0c1117"
BORDER_SUBTLE  = "#2b3542"
BORDER_DEFAULT = "#394656"
BORDER_ACTIVE  = "#cfb68b"

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
SCRUB_HEAD   = "#cfb68b"
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
    parent.setPalette(palette)
    parent.setAutoFillBackground(True)
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


# ── 공통 QSS 스니펫 ──────────────────────────────────────────────
def qss_primary_btn() -> str:
    return (
        f"QPushButton{{background:{TEXT_PRIMARY};color:{BG_BASE};border:1px solid {TEXT_PRIMARY};"
        "border-radius:9px;padding:10px 24px;min-height:18px;font-size:14px;font-weight:700;}"
        f"QPushButton:hover{{background:{WHITE};border-color:{WHITE};}}"
        f"QPushButton:pressed{{background:{BORDER_ACTIVE};border-color:{BORDER_ACTIVE};}}"
        f"QPushButton:focus{{border:1px solid {BORDER_ACTIVE};}}"
        f"QPushButton:disabled{{background:{BG_SURFACE_ALT};color:{TEXT_DIM};border-color:{BORDER_SUBTLE};}}"
    )


def qss_ghost_btn() -> str:
    return (
        f"QPushButton{{background:{BG_SURFACE_ALT};color:{TEXT_BODY};"
        f"border:1px solid {BORDER_DEFAULT};border-radius:7px;padding:7px 12px;min-height:18px;font-size:12px;}}"
        f"QPushButton:hover{{background:{BORDER_DEFAULT};color:{TEXT_PRIMARY};}}"
        f"QPushButton:pressed{{background:{BG_INSET};border-color:{BORDER_ACTIVE};}}"
        f"QPushButton:focus{{border-color:{BORDER_ACTIVE};}}"
        f"QPushButton:checked{{background:{TEXT_PRIMARY};color:{BG_BASE};border-color:{TEXT_PRIMARY};}}"
        f"QPushButton:disabled{{background:{BG_INSET};color:{TEXT_DIM};border-color:{BORDER_SUBTLE};}}"
    )


def qss_input() -> str:
    return (
        f"QLineEdit{{background:{BG_SURFACE};color:{TEXT_PRIMARY};"
        f"border:1px solid {BORDER_DEFAULT};border-radius:9px;padding:12px;font-size:14px;"
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
