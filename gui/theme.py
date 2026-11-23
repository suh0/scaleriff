"""다크 스튜디오 디자인 토큰. 현행 기준: 이 파일."""
from __future__ import annotations
import functools
import math
import os
import random
import time
from PyQt6.QtCore import Qt, QPointF, QRectF, QSize, QTimer
from PyQt6.QtGui import (QFontDatabase, QPalette, QColor, QPainter, QLinearGradient, QRadialGradient, QPen, QIcon,
                         QImage, QPixmap, QRegion)
from PyQt6.QtWidgets import QApplication, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QPushButton

# ── §3.1 표면 / 배경 ─────────────────────────────────────────────
BG_BASE        = "#0d1421"
BG_SURFACE     = "#151e2e"
BG_SURFACE_ALT = "#1e283a"
BG_INSET       = "#0a0f19"
BORDER_SUBTLE  = "#232f44"
BORDER_DEFAULT = "#2e3c55"
ACCENT         = "#5b84ff"   # 남색 배경 위 포인트 파랑(주 버튼·포커스·선택)
ACCENT_LIGHT   = "#8b9cff"
NEON           = "#8b7dff"   # 연주 무대 네온(레일선·흐르는 점선·재생바 패널) — 보라빛 파랑
NEON_LIGHT     = "#d4ceff"   # 네온 심(가장 밝은 선)·재생 헤드
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
# 글자마다 앞에서부터 글리프가 있는 폰트를 쓴다: 영문·숫자는 Segoe UI, 한글은 Segoe UI에 없어 Pretendard로.
FONT_SANS_EN = "Segoe UI"
FONT_SANS_KR = "Pretendard"     # 본고딕보다 획이 또렷한 UI용 한글 고딕(OFL)
FONTS    = [FONT_SANS_EN, FONT_SANS_KR]            # QFont(FONTS, ...)
FONT_CSS = f"'{FONT_SANS_EN}','{FONT_SANS_KR}'"    # QSS font-family 값


@functools.cache   # 창을 만들 때마다 불려도 한 번만 등록
def load_fonts():
    """assets/fonts/*.ttf|otf(Pretendard) 번들 로드 — 다른 PC에 설치돼 있지 않아도 같게 보인다(§4).
    Segoe UI는 Windows 기본 폰트(재배포 불가)라 번들하지 않는다."""
    # Windows offscreen 플러그인은 시스템 폰트 목록을 자동으로 읽지 않는다 — 번들 등록 전에 판단.
    offscreen = os.name == "nt" and not QFontDatabase.families()
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "assets", "fonts")
    if os.path.isdir(d):
        for fn in os.listdir(d):
            if fn.lower().endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(d, fn))
    if offscreen:
        fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf"):
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


_BACKDROP = {}   # 파일명 → 원본, (파일명, w, h) → 그 크기로 채운 픽스맵(창·연주 무대 등 몇 개)


def paint_backdrop(p: QPainter, w: float, h: float, name: str = "backdrop.webp"):
    """배경: assets/<name>을 비율 유지로 꽉 채우고 넘치는 쪽은 가운데 기준으로 자름.
    기본 = 공통 배경(시작·학습 설정·박자 조정), 연주 무대는 stage_backdrop.webp.
    이미지가 없으면 남색 그라데이션 + 모서리 원."""
    img = _BACKDROP.get(name)
    if img is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        img = _BACKDROP[name] = QImage(os.path.join(base, "assets", name))
    if not img.isNull():
        # 화면 실제 픽셀로 맞춘다(배율 125%면 1.25배) — 논리 크기로 줄이면 OS가 다시 늘려 흐려진다
        dpr = p.device().devicePixelRatioF()
        size = (int(w * dpr) + 1, int(h * dpr) + 1)
        pix = _BACKDROP.get((name, *size))
        if pix is None:
            scaled = img.scaled(*size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                Qt.TransformationMode.SmoothTransformation)
            pix = QPixmap.fromImage(scaled.copy((scaled.width() - size[0]) // 2,
                                                (scaled.height() - size[1]) // 2, *size))
            pix.setDevicePixelRatio(dpr)
            if len(_BACKDROP) > 6:          # 창 크기 바꾸는 중 쌓인 것 정리(원본은 남김)
                originals = {k: v for k, v in _BACKDROP.items() if isinstance(k, str)}
                _BACKDROP.clear()
                _BACKDROP.update(originals)
            _BACKDROP[(name, *size)] = pix
        p.drawPixmap(0, 0, pix)
        return
    g = QLinearGradient(0, 0, w * 0.3, h)
    g.setColorAt(0, QColor("#121b2c"))
    g.setColorAt(1, QColor(BG_BASE))
    p.fillRect(0, 0, int(w) + 1, int(h) + 1, g)
    r = max(w, h) * 0.32
    for c in (QPointF(-r * 0.35, -r * 0.45), QPointF(w + r * 0.3, h + r * 0.25)):
        rg = QRadialGradient(c, r)
        rg.setColorAt(0.0, QColor(120, 150, 230, 4))
        rg.setColorAt(1.0, QColor(120, 150, 230, 15))
        p.setBrush(rg)
        p.setPen(QPen(QColor(140, 165, 255, 20), 1.2))
        p.drawEllipse(c, r, r)


FALL_COUNT = 7      # 떨어지는 빛 기둥 수
FLY_COUNT = 26      # 반딧불 수
FRAME_MS = 16       # ~60fps. 위치는 프레임 수가 아니라 시각으로 계산(프레임이 밀려도 속도 일정)


def _bar_pixmap(w, h, dpr):
    """빛 기둥: 위는 투명 → 아래로 밝아지고 바닥 모서리가 가장 밝음, 둘레 은은한 번짐. 여백 m 포함."""
    m = 8
    pix = QPixmap(int((w + 2 * m) * dpr) + 1, int((h + 2 * m) * dpr) + 1)
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    for k in (8, 6, 4, 2):                       # 번짐: 바깥일수록 옅은 테 여러 겹
        g = QLinearGradient(0, m, 0, m + h + k)
        g.setColorAt(0, QColor(91, 132, 255, 0))
        g.setColorAt(1, QColor(91, 132, 255, 12))
        p.fillRect(QRectF(m - k, m, w + 2 * k, h + k), g)
    g = QLinearGradient(0, m, 0, m + h)
    g.setColorAt(0, QColor(110, 145, 255, 0))
    g.setColorAt(0.6, QColor(110, 145, 255, 110))
    g.setColorAt(1, QColor(140, 170, 255, 200))
    p.fillRect(QRectF(m, m, w, h), g)
    p.fillRect(QRectF(m, m + h - 2, w, 2), QColor(200, 215, 255, 220))
    p.end()
    return pix, m


def _fly_pixmap(d, dpr):
    """반딧불: 흰빛 심 + 파란 번짐."""
    pix = QPixmap(int(d * dpr) + 1, int(d * dpr) + 1)
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    g = QRadialGradient(QPointF(d / 2, d / 2), d / 2)
    g.setColorAt(0, QColor(225, 235, 255, 255))
    g.setColorAt(0.16, QColor(130, 165, 255, 200))
    g.setColorAt(0.45, QColor(91, 132, 255, 45))
    g.setColorAt(1, QColor(91, 132, 255, 0))
    p.fillRect(QRectF(0, 0, d, d), g)
    p.end()
    return pix


class Backdrop(QWidget):
    """전 화면 공통 배경 + 떨어지는 빛 기둥·반딧불.

    스프라이트는 한 번 구운 픽스맵을 시각 t로 옮기고 투명도만 바꾼다. 화면들은 투명이라 배경 전체를
    다시 그리면 위 위젯도 모두 다시 그려짐 → 스프라이트의 (지난 자리 ∪ 새 자리)만 update.
    연주화면(무대가 덮음)·숨김·동작 줄이기에선 멈춘다(set_running).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._t = time.perf_counter()
        self._areas = QRegion()          # 지난 프레임에 스프라이트가 그려진 자리
        self._show = False
        self._frame = []                 # 지금 프레임 (픽스맵, 사각형, 투명도) — _tick이 계산, 그리기는 재사용
        self._sprites = None             # ((dpr, 배율), 기둥 픽스맵들, 반딧불 픽스맵)
        rng = random.Random(11)
        # 기둥: (주기 s, 위상, 폭, 높이) — 위에서 나타나 천천히 내려오다 사라지고, 다음 주기엔 다른 x
        self._falls = [(rng.uniform(16, 28), rng.random(), rng.uniform(12, 34), rng.uniform(90, 260))
                       for _ in range(FALL_COUNT)]
        # 반딧불: 기준 위치 + 서로 다른 주기의 sin 두 개(무작위 걸음은 떨려 보임) + 느린 상승 + 깜빡임
        self._flies = [dict(x=rng.random(), y=rng.random(), ax=rng.uniform(0.015, 0.04), ay=rng.uniform(0.02, 0.05),
                            px=(rng.uniform(9, 17), rng.uniform(5, 9)), py=(rng.uniform(11, 19), rng.uniform(6, 10)),
                            ph=[rng.uniform(0, 6.283) for _ in range(5)], rise=rng.uniform(0.004, 0.012),
                            size=rng.uniform(10, 20), tw=rng.uniform(2.5, 5.5))
                       for _ in range(FLY_COUNT)]
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)   # 기본 Coarse는 Windows에서 ~15.6ms 단위로 뭉개짐
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

    def set_running(self, on: bool):
        self._running = on
        self._sync()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._sync()

    def _sync(self):
        if self._running and self.isVisible():
            if not self._timer.isActive():
                self._timer.start()
                self._tick()
        else:
            self._timer.stop()
            self._show = False
            self._frame = []
            self.update(self._areas)
            self._areas = QRegion()

    def _tick(self, now=None):
        app = QApplication.instance()
        still = bool(app and app.property("reduceMotion")) or self.window().isMinimized()
        self._timer.setInterval(500 if still else FRAME_MS)      # 동작 줄이기 중엔 켜졌는지만 가끔 확인
        self._t = time.perf_counter() if now is None else now
        self._show = not still
        self._frame = self._scene() if self._show else []     # 다시 그릴 영역과 그릴 위치가 같은 시각
        new = QRegion()
        for _, target, _ in self._frame:
            new |= QRegion(target.toAlignedRect().adjusted(-1, -1, 1, 1))
        dirty = self._areas | new
        if not dirty.isEmpty():
            self.update(dirty)
        self._areas = new

    def _pixmaps(self):
        dpr, s = self.devicePixelRatioF(), self.height() / 740
        if self._sprites is None or self._sprites[0] != (dpr, s):
            bars = [_bar_pixmap(bw * s, bh * s, dpr) for _, _, bw, bh in self._falls]
            self._sprites = ((dpr, s), bars, _fly_pixmap(24 * s, dpr))
        return self._sprites

    def _scene(self):
        """지금 시각의 (픽스맵, 화면 사각형, 투명도) 목록."""
        (_, s), bars, fly = self._pixmaps()
        w, h, t, out = self.width(), self.height(), self._t, []
        for i, ((period, phase, bw, bh), (pix, m)) in enumerate(zip(self._falls, bars)):
            cycle = t / period + phase
            n, u = math.floor(cycle), cycle % 1.0
            rng = random.Random(i * 7919 + n)                 # 주기마다 새 자리(상태 없이 시각만으로)
            x, alpha, end = rng.uniform(0.03, 0.97) * w, rng.uniform(0.45, 0.85), rng.uniform(0.55, 0.9) * h
            y = -bh * s + u * (end + bh * s)
            fade = min(1.0, u / 0.15, (1 - u) / 0.3)          # 위에서 서서히 나타나 끝에서 사라짐
            out.append((pix, QRectF(x - m, y - m, bw * s + 2 * m, bh * s + 2 * m), alpha * fade * fade))
        for f in self._flies:
            px, py, ph = f["px"], f["py"], f["ph"]
            x = f["x"] + f["ax"] * (0.6 * math.sin(6.283 * t / px[0] + ph[0]) + 0.4 * math.sin(6.283 * t / px[1] + ph[1]))
            y = (f["y"] - f["rise"] * t) % 1.1 - 0.05 \
                + f["ay"] * (0.6 * math.sin(6.283 * t / py[0] + ph[2]) + 0.4 * math.sin(6.283 * t / py[1] + ph[3]))
            d = f["size"] * s
            glow = (0.5 + 0.5 * math.sin(6.283 * t / f["tw"] + ph[4])) ** 2
            out.append((fly, QRectF(x * w - d / 2, y * h - d / 2, d, d), 0.25 + 0.75 * glow))
        return out

    def paint_scene(self, p: QPainter, w: float, h: float):
        """배경 그림 + 스프라이트."""
        paint_backdrop(p, w, h)
        if not self._show:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)   # 소수 좌표 — 느린 반딧불이 1px씩 끊기지 않게
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for pix, target, alpha in self._frame:
            p.setOpacity(alpha)
            p.drawPixmap(target, pix, QRectF(pix.rect()))
        p.restore()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.paint_scene(p, self.width(), self.height())


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


def tinted_icon(name: str, color: str, size: int = 28) -> QIcon:
    """assets/icons/<name>의 currentColor를 color로 칠한 아이콘. 고배율 화면에서도 또렷하게 3배로 그린다."""
    from PyQt6.QtCore import QByteArray
    from PyQt6.QtSvg import QSvgRenderer
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icons", name)
    with open(path, encoding="utf-8") as f:
        svg = f.read().replace("currentColor", color)
    pix = QPixmap(size * 3, size * 3)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    return QIcon(pix)


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


def bare_icon_btn(icon_name: str, tip: str, parent=None) -> QPushButton:
    """배경·테두리 없는 흰 아이콘 버튼(모든 화면의 ←·⚙, 연주 화면 리프모드). 40×40, 아이콘 28.
    이름(accessibleName)·툴팁 = tip. 누르면 살짝 내려간다."""
    btn = QPushButton(parent)
    btn.setIcon(tinted_icon(icon_name, TEXT_PRIMARY))
    btn.setIconSize(QSize(28, 28))
    btn.setFixedSize(40, 40)
    btn.setStyleSheet("QPushButton{background:transparent;border:none;padding:0;}"
                      f"QPushButton:focus{{border-bottom:2px solid {ACCENT};}}"
                      "QPushButton:pressed{padding-top:2px;}")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setToolTip(tip)
    btn.setAccessibleName(tip)
    return btn


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
        f"QWidget{{font-family:{FONT_CSS};font-size:13px;color:{TEXT_BODY};}}"
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
