"""[3] 메인 화면 = 플레이어 — ScaleRiff (리듬게임형 원근 하이웨이).

타임라인을 재생하며 위젯을 갱신만 한다(§4: 재분석 없음).
레이아웃: 원근 무대(건반+노드 레인) 위에 왼쪽 벽(곡 정보·뒤로) · 상단 가운데(현재/다음 코드)
        · 오른쪽 벽(재생·리프모드·설정: 박자·코드 조정, 입력·소리) · 숨김 재생바(스페이스로 표시)
"""
from __future__ import annotations

import bisect
import statistics
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QDialog, QFormLayout, QSlider, QCheckBox, QMessageBox
)
from PyQt6.QtCore import pyqtSignal, Qt, QPoint, QPointF, QRect, QSize, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut

from player.timeline import Timeline
from player.playhead import Playhead
from player.note_synth import shared_player
from analyze.theory import degree_number
from ml.model import load_model
from ml.generate import _landing_pc, riff_blocks

from gui import theme as T
from gui.anim import open_curtain, reduced_motion, set_reduced_motion
from gui.widgets.elided_label import ElidedLabel
from gui.widgets.piano import MIDI_HIGH, MIDI_LOW, PianoWidget
from gui.widgets.scrub_bar import ScrubBar
from gui.widgets.falling_notes import FallingNotes
from gui.widgets.chord_header import ChordHeader
from gui.widgets.stage import Stage
from gui.riff_dialog import RiffDialog, block_goal, landing_goals
from gui.widgets.play_guide import PlayGuide
from gui.widgets import gl_stage

TAP_COUNT = 8   # 싱크 보정 탭 횟수
ASSETS = Path(__file__).resolve().parents[1] / "assets"   # 가이드 이미지(tools/guide_shots.py로 생성)


def tap_offset(taps, beats):
    """탭 시각이 가장 가까운 박에서 늦은 정도의 중앙값(초) = 출력 지연 + 손 반응."""
    devs = []
    for t in taps:
        i = bisect.bisect_left(beats, t)
        devs.append(t - min(beats[max(0, i - 1):i + 1], key=lambda b: abs(b - t)))
    return statistics.median(devs)


def _in_scale(seg):
    """건반에 강조할 (코드톤, 근음) — 고른 스케일 안의 음만(밖이면 근음 None)."""
    ns, root = set(seg.note_set), seg.chord.root % 12
    return [pc for pc in seg.chord_tones() if pc in ns], (root if root in ns else None)


def _fmt_sec(sec: float) -> str:
    s = max(0, int(sec))
    return f"{s // 60:02d}:{s % 60:02d}"


class MainScreen(QWidget):
    backToSetupRequested = pyqtSignal()
    backToLinkRequested = pyqtSignal()
    midiPortRequested = pyqtSignal(str)
    beatEditRequested = pyqtSignal()   # 설정 창 '박자 조정'(창을 닫은 뒤)
    chordEditRequested = pyqtSignal()  # 설정 창 '코드 수정'(창을 닫은 뒤)
    syncChanged = pyqtSignal(int)      # 싱크 보정(ms) 변경 — 저장은 앱이

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl: Timeline | None = None
        self.playhead: Playhead | None = None
        self.note_player = shared_player()
        self._last_idx = -1
        self._mode = "guide"               # guide ↔ practice(리프연습)
        self._ml_model = load_model()      # 부트스트랩/학습 모델(없으면 규칙 폴백)
        # 재생 헤드에 동기화된 리프 이벤트(절대초, midi) — 일시정지/시킹과 함께 동작(§2)
        self._riff_events: list[tuple[float, int, bool]] = []   # (절대초, midi, 프로그램 차례)
        self._riff_times: list[float] = []
        self._riff_durations: list[float] = []
        self._riff_idx = 0                 # 프로그램 차례 리프음 재생 커서
        self._landing_spans: list[tuple[float, float, str]] = []   # 착지음 리프 블록(시작, 끝, 목표) — 리프모드 목표음 강조
        self._held_keys = set()
        self._input_volume = .8
        self._audio_volume = .8
        self._midi_ports = []
        self._midi_name = ""
        self._seeking = False
        self._sync_sec = 0.0              # 싱크 보정: 화면·판정을 이만큼 늦춰 들리는 소리에 맞춤
        self._monitor_seg = None          # 모니터박스에 표시 중인 현재 구간
        self._monitor_prev = ""          # push 동안 밀려나는 이전 코드명
        self.guide = None                # 첫 진입 가이드(PlayGuide) — 떠 있는 동안만

        self.content = T.compact_content(self)
        # 원근 무대를 한 칸에 깔고 같은 칸에 HUD를 정렬로 겹친다(이미지형 하이웨이 배치).
        root = QGridLayout(self.content)
        root.setContentsMargins(0, 0, 0, 0)

        # ── 무대: 건반+노드 레인(원근). PianoWidget·FallingNotes는 상태 모델 ──
        self.piano = PianoWidget()
        self.piano.notePlayed.connect(self.on_midi_note)
        self.riff = FallingNotes(self.piano)
        self.stage = Stage(self.piano, self.riff)
        root.addWidget(self.stage, 0, 0)
        # 실제 화면이면 무대는 GL 창이 그리고(60fps), HUD는 그 위 투명 도구 창으로(첫 표시 때 _enter_hud)
        self.gl_stage = gl_stage.GLStage(self.stage) if gl_stage.available() else None
        if self.gl_stage is not None:
            self.gl_stage.frameSwapped.connect(self._on_frame)
        self.hud = None
        self._hud_items = []                # (위젯, 정렬) — 무대와 같은 칸에 겹치는 HUD

        # ── 왼쪽 위: [<](배경 없는 아이콘) + 곡 제목 + 'D minor | 87 BPM' + 'D 마이너 펜타토닉 스케일' ──
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(T.PAD_H + 6, 20, 0, 0)
        lv.setSpacing(4)
        self.back_btn = T.bare_icon_btn("chevron-left.svg", "학습 설정으로")
        self.back_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.back_btn.clicked.connect(self.backToSetupRequested.emit)
        lv.addWidget(self.back_btn)
        lv.addSpacing(6)
        self.song_lbl = ElidedLabel("—")
        self.song_lbl.setFixedWidth(340)
        self.song_lbl.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:{T.FONT_CSS};font-size:21px;font-weight:700;")
        lv.addWidget(self.song_lbl)
        self.info_lbl = QLabel("—")                     # 키 | BPM (지금 위치·전체 길이는 재생바에)
        self.info_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-family:{T.FONT_CSS};font-size:21px;")
        lv.addWidget(self.info_lbl)
        self.scale_lbl = QLabel("")                     # 학습 설정에서 고른 스케일
        self.scale_lbl.setStyleSheet(self.info_lbl.styleSheet())
        lv.addWidget(self.scale_lbl)
        root.addWidget(left, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._hud_items.append((left, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft))

        # ── 상단 가운데: 현재/다음 코드 ──
        self.chord_hdr = ChordHeader()
        hdr_wrap = QWidget()                # 위 여백 = 천장과 레일 상단 사이에 오게(_place_chord_hdr)
        self._hdr_box = QVBoxLayout(hdr_wrap)
        self._hdr_box.setContentsMargins(0, 0, 0, 0)
        self._hdr_box.addWidget(self.chord_hdr)
        root.addWidget(hdr_wrap, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self._hud_items.append((hdr_wrap, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter))

        # ── 오른쪽 위: [⚙] + 리프모드(AI를 순환 화살표가 감싼 아이콘, 켜지면 네온색) ──
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 20, T.PAD_H, 0)
        rv.setSpacing(20)
        self.settings_btn = T.bare_icon_btn("settings.svg", "설정")
        self.settings_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.settings_btn.setAccessibleName("설정 — 박자·코드 조정, 입력·소리")
        self.settings_btn.clicked.connect(self._show_settings)
        rv.addWidget(self.settings_btn, 0, Qt.AlignmentFlag.AlignRight)
        self.riff_btn = T.bare_icon_btn("riff-ai.svg", "리프모드")
        self.riff_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.riff_btn.setIconSize(QSize(32, 32))
        self.riff_btn.clicked.connect(self._toggle_riff_mode)
        rv.addWidget(self.riff_btn, 0, Qt.AlignmentFlag.AlignRight)
        root.addWidget(right, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self._hud_items.append((right, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight))

        # ── 가운데 재생 아이콘: 멈춤일 때만 반투명하게 ──
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(112, 112)
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.play_btn.setAccessibleName("재생")
        self.play_btn.setToolTip("재생 (스페이스)")
        self.play_btn.setStyleSheet(
            "QPushButton{background:transparent;color:rgba(255,255,255,0.55);"
            "border:none;font-size:44px;padding:0 0 0 8px;"
            "min-width:108px;max-width:108px;min-height:108px;max-height:108px;}"
            "QPushButton:hover{background:transparent;color:rgba(255,255,255,0.8);}")
        self.play_btn.clicked.connect(self._toggle_play)
        root.addWidget(self.play_btn, 0, 0, Qt.AlignmentFlag.AlignCenter)
        self._hud_items.append((self.play_btn, Qt.AlignmentFlag.AlignCenter))

        # ── 재생바: 건반 아래 받침 패널(Stage가 그림) 안쪽에 항상 표시 — 자리는 _place_scrub ──
        self.scrub = ScrubBar()
        self.scrub.seekRequested.connect(self._on_seek)
        self.scrub_row = QWidget(self.content)     # 레이아웃 밖: 무대 원근에 맞춘 패널 자리에 직접 놓는다
        scrub_row = QHBoxLayout(self.scrub_row)
        scrub_row.setSpacing(18)
        self.bar_play_btn = QPushButton("▶")
        self.bar_play_btn.setFixedSize(32, 32)
        self.bar_play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.bar_play_btn.setAccessibleName("재생/일시정지")
        self.bar_play_btn.setToolTip("재생/일시정지 (스페이스)")
        self.bar_play_btn.setStyleSheet(
            f"QPushButton{{background:transparent;border:none;color:{T.TEXT_PRIMARY};font-size:18px;}}"
            f"QPushButton:hover{{color:{T.NEON_LIGHT};}}")
        self.bar_play_btn.clicked.connect(self._toggle_play)
        self.pos_lbl = QLabel("00:00")
        self.total_time_lbl = QLabel("00:00")
        for label in (self.pos_lbl, self.total_time_lbl):
            label.setStyleSheet(
                f"color:{T.TEXT_PRIMARY};font-family:{T.FONT_CSS};font-size:15px;")
        scrub_row.addWidget(self.bar_play_btn)
        scrub_row.addWidget(self.pos_lbl)
        scrub_row.addWidget(self.scrub, 1)
        scrub_row.addWidget(self.total_time_lbl)
        root.setRowStretch(0, 1)            # 남는 높이는 전부 무대
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # 스페이스 = 재생/일시정지(포커스된 버튼 클릭보다 먼저 처리)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self._on_space,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def showEvent(self, e):
        super().showEvent(e)
        if self.gl_stage is not None and self.hud is None:
            self._enter_hud()
        # 연주 가이드와 건반은 즉시 표시한다. 무대엔 커튼이 열리는 연출(창 복원 같은 자발적 표시는 제외).
        if not e.spontaneous():
            self._open_curtain()            # GL 무대면 HUD 창은 커튼이 끝난 뒤에 뜬다
        elif self.hud is not None:
            self.hud.sync()

    def _enter_hud(self):
        """GL 무대: 무대 칸에 겹친 HUD를 투명 도구 창으로 옮긴다(네이티브 GL 창 밑에선 Qt가 안 그림). 앱 창에 딸려야
        하므로 첫 표시 때(이때 window()가 앱 창)."""
        hud = self.hud = gl_stage.HudWindow(self.stage)
        hud.setPalette(self.palette())
        grid = QGridLayout(hud)
        grid.setContentsMargins(0, 0, 0, 0)
        for widget, align in self._hud_items:
            grid.addWidget(widget, 0, 0, align)
        self.scrub_row.setParent(hud)
        self.scrub_row.show()
        self.gl_stage.mirror(self.chord_hdr)            # 계속 움직이는 코드 표시는 GL이 그린다(HUD 창은 거의 안 바뀜)
        QTimer.singleShot(0, self._place_chord_hdr)
        QTimer.singleShot(0, self._place_scrub)

    def _overlay(self):
        """HUD·가이드·커튼이 놓이는 위젯 — GL 무대면 HUD 창, 아니면 이 화면."""
        return self.hud if self.hud is not None else self

    def _from_stage(self, root, pt):
        """무대 좌표 → root 좌표(HUD 창은 다른 최상위 창이라 화면 좌표를 거친다)."""
        return root.mapFromGlobal(self.stage.mapToGlobal(pt))

    def paint_native(self, p, origin):
        """화면 전환 스냅샷에 위젯 grab이 못 잡는 GL 무대·HUD 창을 덧그린다(origin = 스냅샷 좌상단 전역 좌표)."""
        if self.stage.gl is not None:
            p.drawImage(self.stage.gl.container.mapToGlobal(QPoint()) - origin, self.stage.gl.grabFramebuffer())
        if self.hud is not None and self.hud.isVisible():
            p.drawPixmap(self.hud.mapToGlobal(QPoint()) - origin, self.hud.grab())

    def _curtain_host(self):
        """커튼이 놓이는 위젯 — GL 무대면 무대(GL 창이 그림), 아니면 이 화면 전체(HUD 위젯까지 덮음)."""
        return self.stage if self.hud is not None else self

    def _open_curtain(self):
        """커튼(맨 앞 — HUD까지 덮음)을 닫았다 연다. 로딩(건반 층·배경 굽기)을 먼저 끝내 커튼이 끊기지 않게 한다."""
        self.stage.prepare()
        if self.hud is None:
            open_curtain(self)
            return
        # GL 무대: 커튼·떠난 화면·HUD 그림을 GL 한 창이 그린다. HUD 창은 커튼 동안 숨긴다.
        hud, stage = self.hud, self.stage
        hud.held = True                     # 이제 앱 창 이동·크기 변경에도 다시 뜨지 않음
        if not hud.isVisible():
            hud.sync()                      # 숨은 채 자리만 맞춤
        hud.layout().activate()
        self._place_chord_hdr()
        self._place_scrub()
        stage.hud_snap = hud.grab()
        self._opening = True                # 이전 커튼 정리(끝내기)가 HUD 창을 띄우지 않게
        try:
            curtain = open_curtain(stage, gl=True)
        finally:
            self._opening = False
        if curtain is None:                 # 효과 축소
            self._show_hud()
            return
        curtain.anim.finished.connect(self._show_hud)

        def go():                           # GL이 로딩 화면(떠난 화면·HUD 그림 + 텍스처 업로드)을 두 번 낸 뒤 시작
            if getattr(stage, "_curtain", None) is curtain and self.isVisible():
                hud.hold(True)
                curtain.start()
                stage.update()
        self._after_frame(lambda: self._after_frame(go))

    def _show_hud(self):
        """커튼이 끝남 → HUD 창을 띄워 지금 그리고, GL이 두 화면 더 낸 뒤 대신 그리던 그림을 치운다(빈 프레임 없음)."""
        if getattr(self, "_opening", False):
            return
        self.hud.hold(False)
        if self.hud.isVisible():
            self.hud.repaint()

        def drop():
            if getattr(self.stage, "_curtain", None) is None:   # 그새 새 커튼이 시작됐으면 그 커튼의 그림
                self.stage.hud_snap = None
                self.stage.update()
        self._after_frame(lambda: self._after_frame(drop))

    def _after_frame(self, fn):
        """GL 창이 다음 화면을 낸 뒤 fn — 층을 맞바꿀 때 새 층이 먼저 화면에 오르고 옛 층을 치운다."""
        gl = self.gl_stage

        def done():
            gl.frameSwapped.disconnect(done)
            fn()
        gl.frameSwapped.connect(done)
        self.stage.update()

    def keyPressEvent(self, e):
        if self.guide is not None and self.hud is not None:   # HUD 창은 포커스를 안 받음 → 가이드 키는 여기서
            self.guide.keyPressEvent(e)
            return
        super().keyPressEvent(e)

    # ── HUD ─────────────────────────────────────────────────────
    def _set_time(self, sec):
        text = _fmt_sec(sec)
        if text != self.pos_lbl.text():              # 초가 바뀔 때만(HUD 다시 그리기 줄임)
            self.pos_lbl.setText(text)

    def _on_space(self):
        if self.guide is not None:        # 가이드 중 스페이스 = 다음(가이드가 처리)
            self.guide.next()
            return
        self._toggle_play()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._place_chord_hdr)   # 무대 원근(레일 상단)이 새 크기로 잡힌 뒤
        QTimer.singleShot(0, self._place_scrub)
        if self.guide is not None:
            self.guide.relayout()

    def _place_chord_hdr(self):
        """코드 표시의 세로 가운데를 천장과 레일(도로) 먼 끝의 중간에."""
        far = self.stage._xf.map(QPointF(self.stage.width() / 2, 0))
        rail_top = self._from_stage(self.chord_hdr.parentWidget().parentWidget(), far.toPoint()).y()
        self._hdr_box.setContentsMargins(0, max(0, rail_top // 2 - self.chord_hdr.height() // 2), 0, 0)

    def _place_scrub(self):
        """재생바를 건반 아래 받침 패널 안쪽(꺾인 양끝 안)에 맞춘다."""
        r = self.stage.bar_rect()
        self.scrub_row.setGeometry(QRect(self._from_stage(self.scrub_row.parentWidget(), r.topLeft()), r.size()))
        side = r.height() // 2 + 6                     # 꺾인 끝 안쪽 여백
        self.scrub_row.layout().setContentsMargins(side, 0, side, 0)
        self.scrub_row.raise_()

    # ── 첫 진입 가이드 ──────────────────────────────────────────
    def show_guide(self):
        """초심자용 단계별 설명. 첫 코드 위치에서 보여주고, 끝나면 예비박(지금의 첫 화면)으로 돌아간다."""
        if not self.tl or not self.tl.segments or self.guide is not None:
            return
        self.pause()
        tonic, _ = self._song_scale()
        # 설명용 자리: 근음이 1번이 아니고 스케일 안인 첫 코드(1번 표시와 근음 표시가 서로 다른 건반에 보이게)
        seg = next((s for s in self.tl.segments if _in_scale(s)[1] not in (None, tonic)), self.tl.segments[0])
        self._seek_to(seg.start_sec + 1e-3)

        root = self._overlay()                         # 가이드가 놓이는 곳(GL 무대면 HUD 창) 좌표로

        def at(widget):
            return lambda: [QRect(root.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0))), widget.size())]

        def keys():
            return [QRect(self._from_stage(root, self.stage.keys_rect().topLeft()), self.stage.keys_rect().size())]

        def dot(color, name):
            return f"<span style='color:{color};font-size:20px;'>●</span> {name}"

        steps = [
            ("어울리는 건반",
             "색이나 번호가 들어온 건반만 치면 어울리는 곡을 칠 수 있습니다.<br>"
             f"어울림 정도: {dot(T.BADGE_ROOT, '파랑')} &gt; {dot(T.BADGE_CHORD, '초록')} &gt; "
             f"{dot(T.BADGE_SCALE, '회색')}<br>"
             "투명한 건반을 치면 어색한 소리가 나기 쉽습니다.", keys, None),
            ("리프모드(따라치기)",
             "연주를 생성하고, 따라 치며 연습할 수 있습니다.", at(self.riff_btn), None),
            ("리프 생성 창",
             "원하는 부분을 다시 생성할 수 있습니다.", None, str(ASSETS / "guide_riff_dialog.png")),
            ("번갈아 따라 치기",
             "프로그램과 번갈아가며 따라쳐보세요.", None, str(ASSETS / "guide_riff_play.png")),
        ]
        def start():
            if self.guide is None and self.isVisible():   # 커튼 도중 화면을 떠났으면 생략
                self.guide = PlayGuide(root, steps)
                self.guide.finished.connect(self._end_guide)

        curtain = getattr(self._curtain_host(), "_curtain", None)
        if curtain is not None:                        # 커튼이 다 걷힌 뒤 시작
            curtain.anim.finished.connect(start)
        else:
            start()

    def _end_guide(self):
        self.guide = None
        self._seek_to(self.tl.count_in_start())                  # 자유연습 첫 상태로 — 커튼이 다시 열리며 시작
        self._open_curtain()

    # ── 리프를 재생에 함께 굽기(재생 헤드 동기) ──────────────────
    def _build_riff_events(self):
        """모든 구간의 리프 음을 (절대초, midi, 프로그램 차례)로 펼쳐 정렬. 곡 타임라인에 '구워' 둔다.

        프로그램 차례(call) 음은 재생 중 항상 소리 내고 낙하하되 판정은 안 하며, 그 마디 레일은 흐리게.
        내 차례 음은 소리 없이 낙하만(내가 친 음만 들림). 착지음 리프 블록은 목표음 강조 구간으로 기록.
        """
        ev: list[tuple[float, int, bool]] = []
        durations = {}
        falling = []
        if self.tl:
            beat = self.tl.beat_sec()
            for seg in self.tl.segments:
                for n in seg.example:
                    onset = self.tl.beat_at(seg.start_sec) + n["beat_pos"]
                    when = self.tl.time_at_beat(onset)
                    ev.append((when, n["midi"], bool(n.get("call"))))
                    durations[ev[-1]] = self.tl.time_at_beat(onset + n.get("dur_beats", .5)) - when
                    pc = n["midi"] % 12
                    if pc in seg.chord_tones():
                        color = T.BADGE_ROOT if pc == seg.chord.root % 12 else T.BADGE_CHORD
                    else:
                        color = T.BADGE_SCALE
                    falling.append((ev[-1][0], n["midi"], color,
                                    self.tl.time_at_beat(onset + n.get("dur_beats", .5)) - when))
            ev.sort(key=lambda e: e[0])
        self._riff_events = ev
        self._riff_times = [t for t, _, _ in ev]
        self._riff_durations = [durations[e] for e in ev]
        self._riff_idx = bisect.bisect_left(self._riff_times, self.playhead.position_sec() if self.playhead else 0.0)
        blocks = riff_blocks(self.tl, self.tl.practice.get("skip_detour")) if any(c for _, _, c in ev) else []
        goals = landing_goals(self.tl) if self.tl else []
        self._landing_spans = [(blk["bars"][0][0], blk["bars"][-1][1], block_goal(goals, i))
                               for i, blk in enumerate(blocks) if block_goal(goals, i)]
        self.riff.set_events(falling, self.tl.beat_sec() if self.tl else 0.5,
                             self.tl.beat_grid() if self.tl else [],
                             [s.start_sec for s in self.tl.segments] if self.tl else [],
                             [(s.start_sec, s.end_sec) for s in self.tl.segments if s.is_detour] if self.tl else [],
                             [span for blk in blocks for span in blk["bars"][::2]],
                             [(s.start_sec, s.end_sec, s.note_set, *_in_scale(s))
                              for s in self.tl.segments
                              if not (s.is_detour and self.tl.practice.get("skip_detour"))] if self.tl else [])

    # ── 타임라인 로드 ────────────────────────────────────────────
    def set_timeline(self, tl: Timeline):
        if self.playhead:
            self.playhead.pause()
            self.playhead.deleteLater()
        self._select_practice("free")
        self.tl = tl
        self._last_idx = -1
        self._monitor_seg = None
        self.chord_hdr.set_detour({s.chord.name for s in tl.segments if s.is_detour})
        self._build_riff_events()          # 리프를 곡에 함께 구움(§2)
        self.stage.set_states(self._stage_states())   # 건반 층은 진입 첫 프레임에 곡 전체를 미리 굽는다
        self.playhead = Playhead(tl.content_end(), tl.audio_ref, self)
        self.playhead.positionChanged.connect(self._on_tick)
        self.playhead.stateChanged.connect(self._on_state)
        self.playhead.errorOccurred.connect(lambda msg: QMessageBox.warning(self, "재생 오류", msg))
        self.playhead.set_volume(self._audio_volume)
        self._held_keys.clear()

        self.song_lbl.setText(tl.title or tl.audio_ref or "내 곡")
        self.info_lbl.setText(f"{tl.key}    |    {tl.bpm:.0f} BPM")
        scale = (tl.practice.get("scale") or {}).get("name")
        self.scale_lbl.setText(f"{scale} 스케일" if scale else "")
        self.scrub.set_timeline(tl)
        self.total_time_lbl.setText(_fmt_sec(tl.total_sec()))
        self._seek_to(tl.count_in_start())   # 처음 = 예비박부터(음수는 무음 프리롤)
        self.scrub.set_position(self.playhead.position_sec())
        self._set_time(self.playhead.position_sec())

    def pause(self):
        if self.playhead:
            self.playhead.pause()
        self.note_player.stop_all()
        self._held_keys.clear()
        self.piano.set_pressed(set())
        self.stage.update()

    # ── 연습 모드 선택 ──────────────────────────────────────────
    def _select_practice(self, mode: str):
        self._mode = "practice" if mode == "riff" else "guide"
        practice = (self._mode == "practice")
        name = "리프모드 해제" if practice else "리프모드"
        self.riff_btn.setToolTip(name)
        self.riff_btn.setAccessibleName(name)
        self.riff_btn.setIcon(T.tinted_icon("riff-ai.svg", T.NEON if practice else T.TEXT_PRIMARY))
        self.riff.show_notes = practice
        if practice:
            self._build_riff_events()
        self.riff.set_position(self.playhead.position_sec() if self.playhead else 0.0)
        self._render_at(self.playhead.position_sec() if self.playhead else 0.0)
        self._on_state(self.playhead.is_playing() if self.playhead else False)

    # ── 리프모드: 4마디마다 1마디 리프(프로그램·나·프로그램·나) 생성 → 확정 시 리프연습 ──
    def _toggle_riff_mode(self):
        """켜기 = 리프 생성 창(확정 시 진입), 해제 = 자유연습 — 둘 다 곡 처음(예비박)으로."""
        if self._mode == "practice":
            self.pause()
            self._select_practice("free")
            self._seek_to(self.tl.count_in_start())
            self._open_curtain()          # 처음부터 다시 = 커튼 다시 열림
        else:
            self._open_riff_dialog()

    def _open_riff_dialog(self):
        if not self.tl:
            return
        self.pause()
        dialog = RiffDialog(self.tl, self._ml_model, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._select_practice("riff")
            self._seek_to(self.tl.count_in_start())
            self._open_curtain()

    # ── 재생 제어 ────────────────────────────────────────────────
    def _toggle_play(self):
        if self.playhead:
            self.playhead.toggle()

    def _on_state(self, playing: bool):
        self.stage.driven = playing          # 재생 중엔 재생 틱 하나로만 그림(반짝이 타이머 멈춤)
        self.stage.clock = self._visual_clock if playing else None   # GL은 그리는 순간 시각으로(vsync 박자)
        if playing:
            self.stage.update()
        if not playing:
            self.stage.beat = None           # 멈춤 = 박 펄스 없이 아지랑이만 숨 쉼
            self.note_player.stop_all()
            self._held_keys.clear()
            self.piano.set_pressed(set())
            self.stage.update()
        self.play_btn.setVisible(not playing)    # 멈춤일 때만 가운데 재생 아이콘
        self.bar_play_btn.setText("❚❚" if playing else "▶")

    def _visual_clock(self):
        """지금 화면에 보일 시각(싱크 보정 반영)과 박 펄스용 (박 위치, 마디당 박) — 재생 틱과 같은 계산."""
        sec = self.playhead.position_sec() - self._sync_sec
        return sec, (self.tl.beat_at(sec), self.tl.time_sig_beats())

    def _on_seek(self, sec: float):
        self._seek_to(sec)

    def _seek_to(self, sec: float):
        if self.playhead:
            self.note_player.stop_all()
            self._held_keys.clear()
            self._seeking = True
            try:
                self.playhead.seek(sec)
            finally:
                self._seeking = False
            self._render_at(sec)
            self._riff_idx = bisect.bisect_left(self._riff_times, sec)   # 과거 음 몰아 재생 방지

    def _frame_hud(self) -> bool:
        """GL 무대 재생 중엔 HUD(재생바·시간·코드 표시)를 화면 교체 직후(_on_frame)에 갱신 — 재생 타이머 박자로 하면
        GL 그리기와 엇갈려 화면 갱신을 놓친다(실측 p95 19 → 25ms). 재생 로직(리프음·곡 끝)은 타이머 그대로."""
        return self.gl_stage is not None and self.stage.driven

    def _on_frame(self):
        if not self._frame_hud() or not self.tl or not self.playhead:
            return
        sec = self.playhead.position_sec()
        if _fmt_sec(sec) != self.pos_lbl.text():        # 재생바·시간 = HUD 창 → 초가 바뀔 때 한 번에(창 갱신 초당 1회)
            self.scrub.set_position(sec)
            self._set_time(sec)
        vis = sec - self._sync_sec
        self._update_scale_preview(vis, self.tl.segment_index_at(vis))

    def _on_tick(self, sec: float):
        if not self._frame_hud():
            self.scrub.set_position(sec)
        if self.tl and self.playhead and self.playhead.is_playing():   # 무대 아지랑이 박 펄스(들리는 위치 기준)
            self.stage.beat = (self.tl.beat_at(sec - self._sync_sec), self.tl.time_sig_beats())
        if self.tl and not self._frame_hud():
            self._set_time(sec)
        self._render_at(sec)   # 구간 변경 시 무거운 갱신
        if self._seeking:
            return
        # 리프 커서는 항상 따라가고, 프로그램 차례 음만 소리(내 차례는 내가 친 음만 들림, 몰아 재생 없음)
        playing = (self._mode == "practice" and self.playhead is not None and self.playhead.is_playing())
        while self._riff_idx < len(self._riff_times) and self._riff_times[self._riff_idx] <= sec:
            _, midi, call = self._riff_events[self._riff_idx]
            if playing and call:
                self.note_player.play_note(midi, self._riff_durations[self._riff_idx], 80)
            self._riff_idx += 1

    # ── 상태 → UI 렌더 (구간 변경 시) ────────────────────────────
    def _render_at(self, sec: float):
        if not self.tl or not self.tl.segments:
            return
        sec -= self._sync_sec            # 화면은 스피커에서 들리는 위치 기준(리프음 발음은 재생 위치 그대로)
        idx = self.tl.segment_index_at(sec)
        self._update_scale_preview(sec, idx, monitor=not self._frame_hud())
        if idx >= 0 and self.tl.practice.get("skip_detour") and self.tl.segments[idx].is_detour:
            idx = -1                     # 제외한 키 밖 코드 = 예비박처럼 곡 스케일만(코드·근음 강조 없음)
        if idx < 0:
            # 코드 없는 구간(예비박 등)도 곡 스케일과 번호는 그대로 보여준다.
            self._last_idx = -1
            self._show_keys(*self._key_display(-1))
            return
        landing = (next((g for a, b, g in self._landing_spans if a <= sec < b), None)
                   if self._mode == "practice" else None)
        if (idx, landing) == self._last_idx:
            return
        self._last_idx = (idx, landing)
        self._show_keys(*self._key_display(idx, landing))
        self.piano.set_pressed({m for _, m in self._held_keys})

    def _key_display(self, idx, landing=None):
        """구간 idx(-1 = 코드 없음: 곡 스케일만)의 건반 표시 (스케일 음, 강조음, 근음, 번호).
        재생 중 표시와 무대 건반 캐시 미리 굽기(_stage_states)가 같은 규칙을 쓴다."""
        tonic, song_notes = self._song_scale()
        if idx < 0:
            return song_notes, [], None, {pc: degree_number(pc, tonic) for pc in song_notes}
        seg = self.tl.segments[idx]
        chord_tones, root = _in_scale(seg)
        if landing:
            target = _landing_pc(seg, landing)   # 착지음 리프 블록에선 목표음만 초록으로 강조(없으면 코드톤)
            chord_tones = [target] if target in chord_tones else chord_tones
        # 번호는 곡 스케일 주음 기준으로 곡 내내 고정(예외 구간 음은 ♭/♯로), 스케일 밖 음은 번호 없음
        return seg.note_set, chord_tones, root, {pc: degree_number(pc, tonic) for pc in seg.note_set}

    def _show_keys(self, notes, tones, root, degrees):
        self.piano.set_scale(notes, tones, root)
        self.piano.set_degrees(degrees)

    def _stage_states(self):
        """자유연습에서 나올 수 있는 건반 표시 전부(제외한 키 밖 코드는 곡 스케일 표시와 같음)."""
        skip = self.tl.practice.get("skip_detour")
        return [self._key_display(-1)] + [self._key_display(i) for i, seg in enumerate(self.tl.segments)
                                          if not (skip and seg.is_detour)]
        # 현재/다음 코드는 모니터박스가 그림(_update_monitor)

    def _song_scale(self):
        """번호 기준 = 학습 설정에서 고른 곡 스케일의 1(주음)과 그 음들. 설정이 없으면 키 주음."""
        scale = self.tl.practice.get("scale") or {}
        return scale.get("root", self.tl.key_root) % 12, list(scale.get("note_set", []))

    def _update_scale_preview(self, sec: float, idx: int, monitor=True):
        """재생 위치 반영: 낙하 노드 위치 + 상단 코드(현재/다음). 다음 스케일 건반 예고는 없음."""
        self.stage.update()
        self.riff.set_position(sec)
        seg = self.tl.segments[idx] if idx >= 0 else None
        if seg is None:      # 예비박: 첫 코드를 다음 코드로 예고
            first = self.tl.segments[0]
            upcoming = first if sec < first.start_sec else None
            boundary = first.start_sec
        else:
            upcoming = self.tl.next_segment(seg)
            boundary = upcoming.start_sec if upcoming else seg.end_sec
        change = seg.start_sec if seg else sec
        if upcoming is not None and boundary > self.tl.content_end():
            upcoming = None
        lead = min(4 * self.tl.beat_sec(), boundary - (seg.start_sec if seg else sec - 4 * self.tl.beat_sec()))
        grow = (sec - boundary + lead) / lead if upcoming and lead > 0 and boundary - lead <= sec < boundary else 0.0
        if monitor:
            self._update_monitor(sec, seg, upcoming, grow, change)

    def _update_monitor(self, sec, seg, upcoming, grow, change):
        """모니터박스 코드 표시 — 재생 중 코드가 바뀌면 이전 코드를 밀어내는 push(0.5박)."""
        if seg is not self._monitor_seg:
            playing = self.playhead is not None and self.playhead.is_playing()
            self._monitor_prev = self._monitor_seg.chord.name if playing and self._monitor_seg else ""
            self._monitor_seg = seg
        push = min(1.0, max(0.0, (sec - change) / (0.5 * self.tl.beat_sec()))) if self._monitor_prev else 1.0
        if push >= 1:
            self._monitor_prev = ""
        self.chord_hdr.set_chords(seg.chord.name if seg else "",
                             upcoming.chord.name if upcoming else "",
                             self._monitor_prev, grow, push)

    # ── 입력 콜백 ────────────────────────────────────────────────
    def on_midi_note(self, midi: int, is_on: bool):
        self.on_midi_event({"type": "note", "pitch": midi, "is_on": is_on,
                            "velocity": 100, "channel": 0})

    def on_midi_event(self, event: dict):
        if not self.tl or self.playhead is None:
            return
        channel = event.get("channel", 0)
        if event.get("type") == "pedal":
            self.note_player.set_pedal(event.get("down", False), channel)
            return
        midi = event.get("pitch", event.get("midi"))
        if midi is None:
            return
        shown = MIDI_LOW <= midi <= MIDI_HIGH   # 두 옥타브 밖 음은 소리만 낸다
        if event.get("is_on", False):
            if shown:
                self._held_keys.add((channel, midi))
                if self._mode == "practice" and self.playhead.is_playing():   # 리프 타격 판정
                    hit = self.riff.judge(midi, self.playhead.position_sec() - self._sync_sec)
                    if hit:
                        self.stage.splash(*hit)
            self.note_player.note_on(midi, round(event.get("velocity", 100) * self._input_volume), channel)
        else:
            self._held_keys.discard((channel, midi))
            self.note_player.note_off(midi, channel)
        self.piano.set_pressed({m for _, m in self._held_keys})
        self.stage.update_keys([midi])     # 원근 화면은 바뀐 건반 영역만 다시 그림

    def set_midi_status(self, ports, name="", error=""):
        self._midi_ports, self._midi_name = list(ports), name
        self.settings_btn.setToolTip(error or (f"MIDI: {name}" if name else "MIDI 미연결 · 화면 건반으로 연습 가능"))

    def _show_settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("설정")
        dialog.setStyleSheet(T.qss_app())
        dialog.setMinimumWidth(440)
        form = QFormLayout(dialog)
        form.setContentsMargins(24, 24, 24, 24)
        form.setVerticalSpacing(14)
        heading = QLabel("설정")
        heading.setStyleSheet(f"color:{T.TEXT_PRIMARY};font-size:22px;font-weight:700;")
        form.addRow(heading)
        # 곡 조정 — 이 창을 닫은 뒤 연다(확정하면 학습 설정으로 돌아감)
        picked = []
        edits = QHBoxLayout()
        for text, signal in (("박자 조정", self.beatEditRequested), ("코드 수정", self.chordEditRequested)):
            btn = QPushButton(text)
            btn.setStyleSheet(T.qss_ghost_btn())
            btn.clicked.connect(lambda _, s=signal: (picked.append(s), dialog.accept()))
            edits.addWidget(btn)
        form.addRow("곡 조정", edits)
        ports = QComboBox()
        ports.addItem("장치를 선택하세요", "")
        for name in self._midi_ports:
            ports.addItem(name, name)
        ports.setCurrentIndex(max(0, ports.findData(self._midi_name)))
        form.addRow("MIDI 장치", ports)
        reconnect = QPushButton("선택 장치 연결 / 새로 검색")
        def reconnect_ports():
            self.midiPortRequested.emit(ports.currentData() or "")
            ports.clear()
            ports.addItem("장치를 선택하세요", "")
            for name in self._midi_ports:
                ports.addItem(name, name)
            ports.setCurrentIndex(max(0, ports.findData(self._midi_name)))
        reconnect.clicked.connect(reconnect_ports)
        form.addRow(reconnect)
        for text, key in (("원곡 음량", "_audio_volume"), ("내 연주 모니터", "_input_volume")):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setValue(round(getattr(self, key) * 100))
            slider.valueChanged.connect(lambda value, k=key: self._set_volume(k, value / 100))
            form.addRow(text, slider)
        # 싱크 보정 — 재생 중에도 바로 반영(창이 열려 있어도 연주화면은 계속 흐름)
        sync = QSlider(Qt.Orientation.Horizontal)
        sync.setRange(-100, 400)
        sync.setValue(round(self._sync_sec * 1000))
        sync.setToolTip("소리보다 화면이 빠르면 오른쪽으로 — 화면과 판정을 늦춥니다")
        sync_lbl = QLabel(f"{sync.value():+d}ms")
        sync_lbl.setFixedWidth(110)          # 안내 문구가 바뀌어도 슬라이더 폭 고정
        tap = QPushButton("박자에 탭")
        tap.setToolTip(f"곡 재생 중 들리는 박자에 맞춰 {TAP_COUNT}번 누르면 자동으로 맞춰요")
        taps = []

        def on_sync(ms):
            self.set_sync_ms(ms)
            self.syncChanged.emit(ms)
            sync_lbl.setText(f"{ms:+d}ms")

        def on_tap():
            beats = self.tl.beat_grid() if self.tl else []
            if not (self.playhead and self.playhead.is_playing() and beats):
                sync_lbl.setText("재생 중에 눌러요")
                return
            taps.append(self.playhead.position_sec())
            if len(taps) < TAP_COUNT:
                sync_lbl.setText(f"탭 {len(taps)}/{TAP_COUNT}")
                return
            sync.setValue(round(tap_offset(taps, beats) * 1000))
            sync_lbl.setText(f"{sync.value():+d}ms")
            taps.clear()

        sync.valueChanged.connect(on_sync)
        tap.pressed.connect(on_tap)          # 눌린 순간(뗄 때 아님)
        sync_row = QHBoxLayout()
        sync_row.addWidget(sync, 1)
        sync_row.addWidget(sync_lbl)
        sync_row.addWidget(tap)
        form.addRow("싱크 보정", sync_row)
        motion = QCheckBox("화면 전환 효과 줄이기")
        motion.setChecked(reduced_motion())
        motion.setToolTip("페이드 전환을 생략합니다. 박자에 맞춘 낙하 가이드와 다음 음 예고는 유지됩니다.")
        motion.toggled.connect(set_reduced_motion)
        form.addRow("화면 효과", motion)
        close = QPushButton("닫기")
        close.setStyleSheet(T.qss_primary_btn())
        close.clicked.connect(dialog.accept)
        form.addRow(close)
        dialog.exec()
        if picked:
            picked[0].emit()

    def set_sync_ms(self, ms: int):
        self._sync_sec = ms / 1000.0
        if self.playhead:
            self._render_at(self.playhead.position_sec())

    def _set_volume(self, key, value):
        setattr(self, key, value)
        if key == "_audio_volume" and self.playhead:
            self.playhead.set_volume(value)
