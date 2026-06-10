"""ScaleRiff 디자인 토큰 — SCALERIFF_DESIGN_SPEC.md v5/v6 단일 출처.

컨셉: Black & White Minimal + 배지(Badge) 시스템.
- 건반 자체 fill/border는 상태와 무관하게 항상 동일
- 상태는 오직 건반 위 작은 배지(동그라미)로만 표시 — 당구공처럼
- 친 건반: 배지 없음 + 도수 텍스트 #f5c842(노랑) + 상태별 border
- light(300) 굵기 금지 — Inter 최소 500, Space Mono 700
"""
from __future__ import annotations
import os
from PyQt6.QtGui import QFontDatabase

# ── §3.1 표면 / 배경 ─────────────────────────────────────────────
BG_BASE        = "#0a0a0a"
BG_SURFACE     = "#141414"
BG_SURFACE_ALT = "#1e1e1e"
BG_INSET       = "#0f0f0f"
BORDER_SUBTLE  = "#2a2a2a"
BORDER_DEFAULT = "#555555"
BORDER_ACTIVE  = "#ffffff"

# ── §3.2 텍스트 ──────────────────────────────────────────────────
TEXT_PRIMARY = "#ffffff"
TEXT_BODY    = "#e0e0e0"
TEXT_MUTED   = "#a0a0a0"
TEXT_DIM     = "#666666"

# ── §3.3 배지 기능색 (키보드 위젯 전용) ─────────────────────────
BADGE_CHORD      = "#22c55e"   # 코드톤 배지 배경 — 초록
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
KEY_PRESSED_CHORD  = "#22c55e"  # 코드톤 친 건반 테두리
KEY_PRESSED_SCALE  = "#888888"  # 스케일음 친 건반 테두리
KEY_PRESSED_OUT    = "#ef4444"  # 스케일 밖 친 건반 테두리
KEY_PRESSED_LABEL  = "#f5c842"  # 친 건반 도수 텍스트 — 노랑

# ── 공통 UI 엘리먼트 ─────────────────────────────────────────────
WHITE        = "#ffffff"
SCRUB_FILL   = "#3a3a3a"
SCRUB_HEAD   = "#ffffff"
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
FONT_SANS_EN = "Inter"
FONT_MONO    = "Space Mono"
FONT_SANS    = "Noto Sans KR"
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


# ── 공통 QSS 스니펫 ──────────────────────────────────────────────
def qss_primary_btn() -> str:
    return (
        f"QPushButton{{background:{WHITE};color:{BG_BASE};border:none;border-radius:10px;"
        f"padding:12px 28px;font-size:15px;font-weight:bold;}}"
        f"QPushButton:hover{{background:{TEXT_BODY};}}"
    )


def qss_ghost_btn() -> str:
    return (
        f"QPushButton{{background:{BG_SURFACE_ALT};color:{TEXT_BODY};"
        f"border:1px solid {BORDER_DEFAULT};border-radius:7px;padding:6px 12px;font-size:12px;}}"
        f"QPushButton:hover{{border:1px solid {BORDER_ACTIVE};color:{TEXT_PRIMARY};}}"
    )


def qss_outline_btn() -> str:
    return (
        f"QPushButton{{background:transparent;color:{TEXT_PRIMARY};"
        f"border:1px solid {BORDER_ACTIVE};border-radius:10px;padding:11px 18px;font-size:14px;}}"
        f"QPushButton:hover{{background:{HOVER_OVERLAY};}}"
    )


def qss_input() -> str:
    return (
        f"QLineEdit{{background:{BG_SURFACE};color:{TEXT_PRIMARY};"
        f"border:1px solid {BORDER_DEFAULT};border-radius:10px;padding:12px;font-size:14px;}}"
        f"QLineEdit:focus{{border:1px solid {BORDER_ACTIVE};}}"
    )
