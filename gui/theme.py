"""ScaleRiff 디자인 토큰 — SCALERIFF_DESIGN_SPEC.md v4 단일 출처.

컨셉: Black & White Minimal.
- 표면/배경: 순흑(#0a0a0a) 기반 회색 계열
- 텍스트: 흰색(#ffffff) 계열, 최저 대비 6.9:1
- 기능색: 코드톤(#22c55e 초록) / 스케일밖(#ef4444 빨강) — 키보드 전용
- 순백 표면 사용 금지(흰 건반조차 #f0f0f0), 배경은 #0a0a0a 고정
- light(300) 굵기 금지 — Inter 최소 500, Space Mono 700
"""
from __future__ import annotations
import os
from PyQt6.QtGui import QColor, QFontDatabase

# ── §3.1 표면 / 배경 ─────────────────────────────────────────────
BG_BASE        = "#0a0a0a"
BG_SURFACE     = "#141414"
BG_SURFACE_ALT = "#1e1e1e"
BG_INSET       = "#0f0f0f"
BORDER_SUBTLE  = "#2a2a2a"
BORDER_DEFAULT = "#555555"
BORDER_ACTIVE  = "#ffffff"   # 선택·hover 강조

# ── §3.2 텍스트 ──────────────────────────────────────────────────
TEXT_PRIMARY = "#ffffff"    # 21:1 — 제목·강조
TEXT_BODY    = "#e0e0e0"    # 16:1 — 본문
TEXT_MUTED   = "#a0a0a0"    # 11:1 — 보조 설명
TEXT_DIM     = "#666666"    # 6.9:1 — 캡션·모노 라벨

# ── 기능색 (키보드 전용 — UI 일반 영역 사용 금지) ────────────────
KEY_CHORD          = "#22c55e"   # 코드톤 — 초록
KEY_CHORD_DARK     = "#14532d"   # 검은 건반 코드톤 fill
KEY_CHORD_LABEL    = "#15803d"   # 코드톤 라벨 (흰 건반)
KEY_CHORD_LABEL_BK = "#4ade80"   # 코드톤 라벨 (검은 건반)
KEY_OUT            = "#ef4444"   # 스케일 밖 — 빨강
KEY_OUT_DARK       = "#450a0a"   # 검은 건반 스케일 밖 fill
KEY_OUT_LABEL      = "#dc2626"   # 스케일 밖 라벨 (흰 건반)
KEY_OUT_LABEL_BK   = "#f87171"   # 스케일 밖 라벨 (검은 건반)

# ── 공통 UI 엘리먼트 ─────────────────────────────────────────────
WHITE  = "#ffffff"
SCRUB_FILL = "#3a3a3a"     # 재생된 구간 fill
SCRUB_HEAD = "#ffffff"     # 스크럽 헤드
GLOW   = "#ffffff"         # 친 건반 글로우 링

# ── 이하는 이전 코드 호환용 별칭 (점진적 제거 예정) ─────────────
TEXT_ACCENT = TEXT_MUTED   # 구 TEXT_ACCENT → TEXT_MUTED 에 매핑
GOLD        = WHITE        # 구 GOLD → 흰색 (재생 버튼 등)
GOLD_LIGHT  = TEXT_BODY    # 구 GOLD_LIGHT → light grey
HEAD        = SCRUB_HEAD   # 구 HEAD → 흰 헤드

# ── §4 폰트 패밀리 ────────────────────────────────────────────────
# v4: Inter(영문) + Space Mono(모노) + Noto Sans KR(한글)
# serif 계열(DM Serif Display, Nanum Myeongjo) 폐기
FONT_SANS_EN = "Inter"          # 제목·워드마크·코드명 (700–900)
FONT_MONO    = "Space Mono"     # 모노 라벨·도수 (700, letter-spacing 2–3px)
FONT_SANS    = "Noto Sans KR"   # 한글 본문 (500–700)
# 구 이름 별칭
FONT_SERIF    = FONT_SANS_EN    # 구 FONT_SERIF → Inter
FONT_SERIF_KR = FONT_SANS       # 구 FONT_SERIF_KR → Noto Sans KR


# ── §5 키보드 상태색 v4 ──────────────────────────────────────────
# 형식: (fill, border_color_or_None, label_color_or_None, border_width_px)
# border_color=None → 테두리 없음

# 흰 건반
KW: dict[str, tuple] = {
    "DEFAULT": ("#f0f0f0",  "#cccccc",          None,                  1.0),
    "SCALE":   ("#e8e8e8",  "#888888",           "#555555",             1.5),
    "CHORD":   ("#ffffff",  KEY_CHORD,           KEY_CHORD_LABEL,       2.0),
    "OUT":     ("#fff1f1",  KEY_OUT,             KEY_OUT_LABEL,         2.0),
    "PRESSED": ("#ffffff",  WHITE,               "#000000",             2.0),
}
# 검은 건반
KB: dict[str, tuple] = {
    "DEFAULT": ("#1a1a1a",      None,            None,                  0.0),
    "SCALE":   ("#2a2a2a",      "#666666",       "#999999",             1.0),
    "CHORD":   (KEY_CHORD_DARK, KEY_CHORD,       KEY_CHORD_LABEL_BK,    1.5),
    "OUT":     (KEY_OUT_DARK,   KEY_OUT,         KEY_OUT_LABEL_BK,      1.5),
    "PRESSED": ("#3a3a3a",      WHITE,           WHITE,                 1.5),
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
    """주요 행동 버튼 — 흰 배경 + 검정 텍스트."""
    return (
        f"QPushButton{{background:{WHITE};color:{BG_BASE};border:none;border-radius:10px;"
        f"padding:12px 28px;font-size:15px;font-weight:bold;}}"
        f"QPushButton:hover{{background:{TEXT_BODY};}}"
    )


def qss_ghost_btn() -> str:
    """보조 버튼 — 어두운 배경 + 테두리."""
    return (
        f"QPushButton{{background:{BG_SURFACE_ALT};color:{TEXT_BODY};"
        f"border:1px solid {BORDER_DEFAULT};border-radius:7px;padding:6px 12px;font-size:12px;}}"
        f"QPushButton:hover{{border:1px solid {BORDER_ACTIVE};color:{TEXT_PRIMARY};}}"
    )


def qss_outline_btn() -> str:
    """외곽선 버튼 — 테두리만, 배경 투명."""
    return (
        f"QPushButton{{background:transparent;color:{TEXT_PRIMARY};"
        f"border:1px solid {BORDER_ACTIVE};border-radius:10px;padding:11px 18px;font-size:14px;}}"
        f"QPushButton:hover{{background:rgba(255,255,255,0.08);}}"
    )


def qss_input() -> str:
    """텍스트 입력 필드."""
    return (
        f"QLineEdit{{background:{BG_SURFACE};color:{TEXT_PRIMARY};"
        f"border:1px solid {BORDER_DEFAULT};border-radius:10px;padding:12px;font-size:14px;}}"
        f"QLineEdit:focus{{border:1px solid {BORDER_ACTIVE};}}"
    )
