"""ScaleRiff 디자인 토큰 — SCALERIFF_DESIGN_SPEC.md 단일 출처.

색(QSS/QColor 공용 HEX) · 폰트 패밀리 · 공통 버튼 QSS · 키보드 Scheme A++.
순백(#ffffff)/순흑(#000000) 표면 금지. 경고색은 빨강 아닌 번트 난색(변경 금지).
"""
from __future__ import annotations
import os
from PyQt6.QtGui import QColor, QFontDatabase

# ── §3.1 표면/배경 (v3 가독성 보정) ─────────────────────────────
BG_BASE = "#14100a"
BG_SURFACE = "#20180c"
BG_SURFACE_ALT = "#261d0e"
BG_INSET = "#0f0c07"
BORDER_SUBTLE = "#4e3c1e"
BORDER_DEFAULT = "#7a5f2a"
BORDER_ACTIVE = "#d4a838"

# ── §3.2 텍스트 (v3: 최저 대비 7:1) ─────────────────────────────
TEXT_PRIMARY = "#f4d98a"
TEXT_BODY = "#d8b87a"
TEXT_ACCENT = "#dca838"
TEXT_MUTED = "#d6b478"
TEXT_DIM = "#c0a060"

GOLD = "#c8962a"           # 재생 버튼 등(§6)
GOLD_LIGHT = "#f4d98a"
HEAD = "#f0a818"           # 스크럽 헤드
GLOW = "#ffd060"           # 친 건반 글로우 링

# ── §4 폰트 패밀리(번들 시 assets/fonts/*.ttf 로드, 없으면 폴백) ──
FONT_SERIF = "DM Serif Display"
FONT_SERIF_KR = "Nanum Myeongjo"
FONT_MONO = "Space Mono"
FONT_SANS = "Noto Sans KR"

# ── §5 키보드 Scheme A++ : 상태 → (fill, border, 라벨텍스트색) ───
# 라벨색은 솔리드(반투명 금지, v2). 밝은 건반=다크, 어두운 건반=크림.
_DARK = QColor("#1a1208")
_CREAM = QColor("#fbf2dc")
# 흰 건반
KW = {
    "DEFAULT": ("#fbf2dc", "#2a1e0c", None),
    "SCALE":   ("#f5d878", "#c89820", _DARK),
    "CHORD":   ("#ee9608", "#b06e00", _DARK),
    "OUT":     ("#9e3410", "#742208", _CREAM),
    "PRESSED": ("#ffb820", "#dc9400", _DARK),
}
# 검은 건반 (어두운 배경 위라 더 진한 톤)
KB = {
    "DEFAULT": ("#2a1f10", "#000000", None),
    "SCALE":   ("#9c7008", "#000000", _CREAM),
    "CHORD":   ("#d68a00", "#000000", _DARK),
    "OUT":     ("#6e2608", "#000000", _CREAM),
    "PRESSED": ("#ee9608", "#000000", _DARK),
}


def load_fonts():
    """assets/fonts/*.ttf|otf 번들 로드(있으면). 시스템 설치에 의존하지 않음(§4)."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "assets", "fonts")
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(d, fn))


# ── 공통 QSS 스니펫 ──────────────────────────────────────────────
def qss_primary_btn() -> str:
    return (f"QPushButton{{background:{GOLD};color:{BG_BASE};border:none;border-radius:10px;"
            f"padding:12px 28px;font-size:15px;font-weight:bold;}}"
            f"QPushButton:hover{{background:{GOLD_LIGHT};}}")


def qss_ghost_btn() -> str:
    return (f"QPushButton{{background:{BG_SURFACE_ALT};color:{TEXT_BODY};"
            f"border:1px solid {BORDER_DEFAULT};border-radius:7px;padding:6px 12px;font-size:12px;}}"
            f"QPushButton:hover{{border:1px solid {BORDER_ACTIVE};color:{TEXT_PRIMARY};}}")


def qss_outline_btn() -> str:
    return (f"QPushButton{{background:transparent;color:{TEXT_PRIMARY};"
            f"border:1px solid {BORDER_ACTIVE};border-radius:10px;padding:11px 18px;font-size:14px;}}"
            f"QPushButton:hover{{background:rgba(200,150,42,0.12);}}")


def qss_input() -> str:
    return (f"QLineEdit{{background:{BG_SURFACE};color:{TEXT_PRIMARY};"
            f"border:1px solid {BORDER_DEFAULT};border-radius:10px;padding:12px;font-size:14px;}}"
            f"QLineEdit:focus{{border:1px solid {BORDER_ACTIVE};}}")
