"""[3] 메인 화면 = 플레이어 — ScaleRiff (리듬게임형 원근 하이웨이).

타임라인을 재생하며 위젯을 갱신만 한다(§4: 재분석 없음).
레이아웃: 원근 무대(건반+노드 레인) 위에 왼쪽 벽(곡 정보·뒤로) · 상단 가운데(현재/다음 코드)
        · 오른쪽 벽(재생·리프모드·설정: 박자·코드 조정, 입력·소리) · 숨김 재생바(스페이스로 표시)
"""
from __future__ import annotations

import bisect
import statistics

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QDialog, QFormLayout, QSlider, QCheckBox, QMessageBox, QSizePolicy
)
from PyQt6.QtCore import pyqtSignal, Qt, QPoint, QPointF, QRect, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut

from player.timeline import Timeline
from player.playhead import Playhead
from player.note_synth import shared_player
from analyze.theory import degree_number, pc_name
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

TAP_COUNT = 8   # 싱크 보정 탭 횟수


def tap_offset(taps, beats):
    """탭 시각이 가장 가까운 박에서 늦은 정도의 중앙값(초) = 출력 지연 + 손 반응."""
    devs = []
    for t in taps:
        i = bisect.bisect_left(beats, t)
        devs.append(t - min(beats[max(0, i - 1):i + 1], key=lambda b: abs(b - t)))
    return statistics.median(devs)


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

        # ── 왼쪽 벽: [←](오른쪽 ⚙와 좌우대칭) + 곡 정보 ──
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(T.PAD_H + 8, 24, 0, 0)
        lv.setSpacing(4)
        self.back_btn = QPushButton("←")
        self.back_btn.setToolTip("학습 설정으로")
        self.back_btn.clicked.connect(self.backToSetupRequested.emit)
        self.back_btn.setFixedSize(48, 48)
        self.back_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.back_btn.setStyleSheet(T.qss_icon_btn())
        lv.addWidget(self.back_btn)
        lv.addSpacing(14)
        self.song_lbl = ElidedLabel("—")
        self.song_lbl.setFixedWidth(240)
        self.song_lbl.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:{T.FONT_CSS};font-size:16px;font-weight:700;")
        lv.addWidget(self.song_lbl)
        key_bpm = QHBoxLayout()
        key_bpm.setSpacing(28)
        for cap in ("KEY", "BPM"):
            col = QVBoxLayout()
            col.setSpacing(4)
            key_bpm.addLayout(col)
            if cap == "KEY":
                self.key_lbl = self._hud_stat(col, cap)
            else:
                self.bpm_lbl = self._hud_stat(col, cap)
        key_bpm.addStretch(1)
        lv.addLayout(key_bpm)
        self.time_lbl = self._hud_stat(lv, "TIME")
        root.addWidget(left, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # ── 상단 가운데: 현재/다음 코드 ──
        self.chord_hdr = ChordHeader()
        hdr_wrap = QWidget()                # 위 여백 = 천장과 레일 상단 사이에 오게(_place_chord_hdr)
        self._hdr_box = QVBoxLayout(hdr_wrap)
        self._hdr_box.setContentsMargins(0, 0, 0, 0)
        self._hdr_box.addWidget(self.chord_hdr)
        root.addWidget(hdr_wrap, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # ── 오른쪽 벽: [⚙] + 리프모드 ──
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 24, T.PAD_H + 8, 0)
        rv.setSpacing(8)
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setAccessibleName("설정 — 박자·코드 조정, 입력·소리")
        self.settings_btn.clicked.connect(self._show_settings)
        self.settings_btn.setFixedSize(48, 48)
        self.settings_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.settings_btn.setStyleSheet(T.qss_icon_btn())
        rv.addWidget(self.settings_btn, 0, Qt.AlignmentFlag.AlignRight)
        rv.addSpacing(6)
        self.riff_btn = QPushButton("리프모드")
        self.riff_btn.clicked.connect(self._toggle_riff_mode)
        self.riff_btn.setFixedSize(116, 36)
        self.riff_btn.setStyleSheet(T.qss_ghost_btn())
        self.riff_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rv.addWidget(self.riff_btn, 0, Qt.AlignmentFlag.AlignRight)
        root.addWidget(right, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

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

        # ── 재생바: 무대 아래 칸에 항상 표시(무대는 그만큼 줄어 건반·레일이 위로) ──
        self.scrub = ScrubBar()
        self.scrub.seekRequested.connect(self._on_seek)
        self.scrub_row = QWidget()
        scrub_row = QHBoxLayout(self.scrub_row)
        scrub_row.setContentsMargins(T.PAD_H, 0, T.PAD_H, 6)
        self.pos_lbl = QLabel("00:00")
        self.total_time_lbl = QLabel("00:00")
        for label in (self.pos_lbl, self.total_time_lbl):
            label.setStyleSheet(
                f"color:{T.TEXT_BODY};font-family:{T.FONT_CSS};font-size:12px;")
        scrub_row.addWidget(self.pos_lbl)
        scrub_row.addWidget(self.scrub, 1)
        scrub_row.addWidget(self.total_time_lbl)
        self.scrub_row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        root.addWidget(self.scrub_row, 1, 0)
        root.setRowStretch(0, 1)            # 남는 높이는 전부 무대
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # 스페이스 = 재생/일시정지(포커스된 버튼 클릭보다 먼저 처리)
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self._on_space,
                  context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def showEvent(self, e):
        super().showEvent(e)
        # 연주 가이드와 건반은 즉시 표시한다. 무대엔 커튼이 열리는 연출(창 복원 같은 자발적 표시는 제외).
        if not e.spontaneous():
            open_curtain(self.stage)

    # ── HUD ─────────────────────────────────────────────────────
    @staticmethod
    def _hud_stat(layout, caption):
        """이미지형 HUD: 자간 넓은 작은 대문자 라벨 + 큰 값."""
        cap = QLabel(caption)
        cap.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:{T.FONT_CSS};font-size:11px;letter-spacing:3px;")
        value = QLabel("—")
        value.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:{T.FONT_CSS};font-size:24px;font-weight:600;")
        layout.addSpacing(6)
        layout.addWidget(cap)
        layout.addWidget(value)
        return value

    def _set_time(self, sec):
        self.pos_lbl.setText(_fmt_sec(sec))
        total = _fmt_sec(self.tl.total_sec()) if self.tl else "00:00"
        self.time_lbl.setText(f"{_fmt_sec(sec)} / {total}")

    def _on_space(self):
        if self.guide is not None:        # 가이드 중 스페이스 = 다음(가이드가 처리)
            self.guide.next()
            return
        self._toggle_play()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._place_chord_hdr)   # 무대 원근(레일 상단)이 새 크기로 잡힌 뒤
        if self.guide is not None:
            self.guide.relayout()

    def _place_chord_hdr(self):
        """코드 표시의 세로 가운데를 천장과 레일(도로) 먼 끝의 중간에."""
        far = self.stage._xf.map(QPointF(self.stage.width() / 2, 0))
        rail_top = self.stage.mapTo(self.content, far.toPoint()).y()
        self._hdr_box.setContentsMargins(0, max(0, rail_top // 2 - self.chord_hdr.height() // 2), 0, 0)

    # ── 첫 진입 가이드 ──────────────────────────────────────────
    def show_guide(self):
        """초심자용 단계별 설명. 첫 코드 위치에서 보여주고, 끝나면 예비박(지금의 첫 화면)으로 돌아간다."""
        if not self.tl or not self.tl.segments or self.guide is not None:
            return
        self.pause()
        tonic, _ = self._song_scale()
        scale = (self.tl.practice.get("scale") or {}).get("name") or self.tl.key
        # 설명용 자리: 근음이 1번이 아닌 첫 코드(1번 표시와 근음 표시가 서로 다른 건반에 보이게)
        seg = next((s for s in self.tl.segments if s.chord.root % 12 != tonic), self.tl.segments[0])
        self._seek_to(seg.start_sec + 1e-3)
        root_no = degree_number(seg.chord.root % 12, tonic)

        def at(widget):
            return lambda: [QRect(widget.mapTo(self, QPoint(0, 0)), widget.size())]

        def keys():
            return [QRect(self.stage.mapTo(self, self.stage.keys_rect().topLeft()), self.stage.keys_rect().size())]

        steps = [
            ("연주 화면에 오신 걸 환영해요",
             "노래에 맞춰 건반으로 즉흥 연주하는 화면이에요.<br>"
             "피아노를 몰라도 괜찮아요. 건반의 <b>숫자</b>와 <b>색</b>만 보면 바로 칠 수 있어요.", None),
            ("건반 치는 법",
             "왼쪽으로 갈수록 낮은 음, 오른쪽으로 갈수록 높은 음이에요.<br>"
             "화면 건반을 <b>마우스로 클릭</b>하거나, <b>MIDI 키보드</b>를 연결해 쳐요.<br>"
             "흰 건반과 검은 건반 모두 똑같이 한 음씩이에요.", keys),
            ("건반 위 숫자 = 스케일 번호",
             f"이 곡은 <b>{scale}</b>로 연습해요. <b>1번 = {pc_name(tonic)}</b>이고, "
             "곡이 끝날 때까지 번호는 바뀌지 않아요.<br>숫자가 있는 건반만 쳐도 곡과 어울려요.", keys),
            ("색으로 보는 음의 역할",
             "<b>파랑·반짝임 = 지금 코드의 근음</b>(가장 안정적인 음)<br>"
             "초록 = 지금 코드를 이루는 음(코드톤)<br>회색 = 스케일 음<br>"
             "<b>투명하게 테두리만 보이는 건반</b>(숫자 없음) = 스케일 밖 음이에요. 이 곡과 덜 어울려서 "
             "누르면 빨갛게 표시되지만 틀린 건 아니에요. 근음은 스케일 밖이어도 파랑으로 보여요.", keys),
            ("지금 코드와 근음 번호",
             "코드는 반주가 지금 울리는 화음이에요. 가운데 큰 글자가 지금 코드, 위 작은 글자가 다음 코드예요.<br>"
             f"<b>'근음 {root_no}번'</b>은 지금 코드의 근음이 스케일 몇 번인지 알려줘요. "
             "코드가 바뀌면 파란 근음 건반도 따라 옮겨가요.", at(self.chord_hdr)),
            ("곡 정보",
             "KEY = 곡의 조, BPM = 빠르기(분당 박 수), TIME = 지금 위치 / 전체 길이예요.<br>"
             "<b>←</b> 버튼은 학습 설정으로 돌아가 스케일을 다시 골라요.", at(self.back_btn.parentWidget())),
            ("재생하기",
             "가운데 <b>▶</b> 또는 <b>스페이스</b>로 재생·정지해요. 곡 앞에 박을 세는 예비박이 있어요.<br>"
             "아래 재생바를 클릭·드래그하면 원하는 위치로 이동해요.",
             lambda: at(self.play_btn)() + at(self.scrub_row)()),
            ("리프모드 — 따라 치기",
             "누르면 리프(짧은 멜로디) 만들기 창이 열려요. <b>듣기</b>·<b>다시 만들기</b>로 고르고 "
             "<b>확정</b>하면 시작해요. '3도/7도 착지 섞기'를 켜면 코드의 3도·7도 음으로 끝나는 리프도 섞여요.<br>"
             "프로그램이 한 마디 치면(어둡고 흐린 블록, 소리로 들려줘요) 다음 마디에 "
             "<b>내가 같은 리프로 따라 쳐요</b>(선명한 색 블록). "
             "블록이 건반에 닿을 때 누르면 PERFECT·EARLY·LATE가 떠요.<br>"
             "'리프모드 해제'로 자유연습에 돌아와요.",
             at(self.riff_btn)),
            ("설정 ⚙",
             "<b>박자 조정</b> — 박이 음악과 어긋나 보일 때<br><b>코드 수정</b> — 표시된 코드가 틀렸을 때<br>"
             "고치고 확정하면 학습 설정으로 돌아와요.<br>"
             "그 밖에 MIDI 키보드 연결, 원곡·내 연주 음량, 화면과 소리가 어긋날 때 맞추는 "
             "<b>싱크 보정</b>('박자에 탭')이 있어요.", at(self.settings_btn)),
            ("이렇게 시작해 보세요",
             "① ▶를 누르고 <b>파란 근음 건반</b>만 박자에 맞춰 눌러 보세요.<br>"
             "② 익숙해지면 <b>숫자 있는 건반</b>으로 넓혀 짧게 쳐 보세요.<br>"
             "③ 더 연습하고 싶으면 <b>리프모드</b>로 따라 쳐 보세요.", None),
        ]
        self.guide = PlayGuide(self, steps)
        self.guide.finished.connect(self._end_guide)

    def _end_guide(self):
        self.guide = None
        self._seek_to(self.tl.count_in_start())                  # 지금의 연주화면 첫 상태로

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
                             [(s.start_sec, s.end_sec, s.note_set, s.chord_tones(), s.chord.root % 12)
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
        self.playhead = Playhead(tl.content_end(), tl.audio_ref, self)
        self.playhead.positionChanged.connect(self._on_tick)
        self.playhead.stateChanged.connect(self._on_state)
        self.playhead.errorOccurred.connect(lambda msg: QMessageBox.warning(self, "재생 오류", msg))
        self.playhead.set_volume(self._audio_volume)
        self._held_keys.clear()

        self.song_lbl.setText(tl.title or tl.audio_ref or "내 곡")
        self.key_lbl.setText(tl.key)
        self.bpm_lbl.setText(f"{tl.bpm:.0f}")
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
        self.riff_btn.setText("리프모드 해제" if practice else "리프모드")
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
            open_curtain(self.stage)          # 처음부터 다시 = 커튼 다시 열림
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
            open_curtain(self.stage)

    # ── 재생 제어 ────────────────────────────────────────────────
    def _toggle_play(self):
        if self.playhead:
            self.playhead.toggle()

    def _on_state(self, playing: bool):
        self.stage.driven = playing          # 재생 중엔 재생 틱 하나로만 그림(반짝이 타이머 멈춤)
        if not playing:
            self.note_player.stop_all()
            self._held_keys.clear()
            self.piano.set_pressed(set())
            self.stage.update()
        self.play_btn.setVisible(not playing)    # 멈춤일 때만 가운데 재생 아이콘

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

    def _on_tick(self, sec: float):
        self.scrub.set_position(sec)
        if self.tl:
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
        self._update_scale_preview(sec, idx)
        tonic, song_notes = self._song_scale()
        if idx >= 0 and self.tl.practice.get("skip_detour") and self.tl.segments[idx].is_detour:
            idx = -1                     # 제외한 키 밖 코드 = 예비박처럼 곡 스케일만(코드·근음 강조 없음)
        if idx < 0:
            # 코드 없는 구간(예비박 등)도 곡 스케일과 번호는 그대로 보여준다.
            self._last_idx = -1
            self.piano.set_scale(song_notes, [])
            self.piano.set_degrees({pc: degree_number(pc, tonic) for pc in song_notes})
            return
        landing = (next((g for a, b, g in self._landing_spans if a <= sec < b), None)
                   if self._mode == "practice" else None)
        if (idx, landing) == self._last_idx:
            return
        self._last_idx = (idx, landing)
        seg = self.tl.segments[idx]
        chord_tones = seg.chord_tones()
        if landing:
            target = _landing_pc(seg, landing)   # 착지음 리프 블록에선 목표음만 초록으로 강조(없으면 코드톤)
            chord_tones = [target] if target is not None else chord_tones
        root = seg.chord.root % 12
        self.piano.set_scale(seg.note_set, chord_tones, root)
        # 번호는 곡 스케일 주음 기준으로 곡 내내 고정(예외 구간 음은 ♭/♯로), 근음은 스케일 밖이어도 번호 표시
        self.piano.set_degrees({pc: degree_number(pc, tonic) for pc in set(seg.note_set) | {root}})
        self.piano.set_pressed({m for _, m in self._held_keys})
        # 현재/다음 코드는 모니터박스가 그림(_update_monitor)

    def _song_scale(self):
        """번호 기준 = 학습 설정에서 고른 곡 스케일의 1(주음)과 그 음들. 설정이 없으면 키 주음."""
        scale = self.tl.practice.get("scale") or {}
        return scale.get("root", self.tl.key_root) % 12, list(scale.get("note_set", []))

    def _update_scale_preview(self, sec: float, idx: int):
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
        caption = ""
        if seg:      # 지금 코드 근음이 곡 스케일 몇 번인지 + 스케일 종류
            number = degree_number(seg.chord.root % 12, self._song_scale()[0])
            caption = f"근음 {number}번" + (f" · {seg.scale.kind}" if seg.scale else "")
        self.chord_hdr.set_chords(seg.chord.name if seg else "", caption,
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
        self.settings_btn.setStyleSheet(T.qss_icon_btn(T.TEXT_PRIMARY if name else T.TEXT_DIM))
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
