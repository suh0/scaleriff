"""[3] 메인 화면 = 플레이어 — ScaleRiff (디자인 스펙 §6.1).

타임라인을 재생하며 위젯을 갱신만 한다(§4: 재분석 없음).
레이아웃: 상단바(뒤로/곡명/BPM) · 코드 HUD(현재 + 다음 가이드 + 카운트인)
        · 리프연습 토글 · 피아노 · 리프 뷰(연습 시) · 스크럽 · 재생
"""
from __future__ import annotations

import bisect

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QComboBox
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QPropertyAnimation, QEasingCurve, QPoint
)

from player.timeline import Timeline
from player.playhead import Playhead
from player.note_synth import NotePlayer
from player.scoring import ScoreEngine
from analyze.theory import degree_number
from ml.model import load_model
from ml.generate import bake_examples

from gui import theme as T
from gui.anim import stagger
from gui.widgets.piano import PianoWidget
from gui.widgets.scrub_bar import ScrubBar
from gui.widgets.mini_guide import MiniGuide
from gui.widgets.riff_view import RiffView
from gui.widgets.countin import CountIn
from gui.widgets.pass_card import PassCard

# 코드/가이드를 재생 위치보다 앞당겨 표시하는 보정값(초). 0 = 보정 없음.
SYNC_LOOKAHEAD_SEC = 0.0


class SlideGuide(QWidget):
    """다음 스케일 미리보기(1옥타브) — 내용이 바뀌는 박에 위에서 내려오며 교체.

    자식(MiniGuide)은 부모 사각형에 클리핑되므로 위(-h)에서 0으로 미끄러져
    들어오는 동안 바깥으로 새지 않는다.
    """

    def __init__(self, w: int = 200, h: int = 58, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self.guide = MiniGuide(self)
        self.guide.setGeometry(0, 0, w, h)
        self._anim = QPropertyAnimation(self.guide, b"pos", self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def set_scale(self, note_set, chord_tones, root: int):
        self.guide.set_scale(note_set, chord_tones, root)
        if self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(QPoint(0, -self.height()))
            self._anim.setEndValue(QPoint(0, 0))
            self._anim.start()
        else:
            self.guide.move(0, 0)

    def clear(self):
        self._anim.stop()
        self.guide.move(0, 0)
        self.guide.clear()


class MainScreen(QWidget):
    backToScoreRequested = pyqtSignal()
    backToLinkRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tl: Timeline | None = None
        self.playhead: Playhead | None = None
        self.note_player = NotePlayer(self)
        self._last_idx = -1
        self._mode = "guide"               # guide ↔ practice(리프연습)
        self.scorer: ScoreEngine | None = None   # 연주 채점(§7.5) — 가이드 모드 전용
        self._ml_model = load_model()      # 부트스트랩/학습 모델(없으면 규칙 폴백)
        # 재생 헤드에 동기화된 리프 이벤트(절대초, midi) — 일시정지/시킹과 함께 동작(§2)
        self._riff_events: list[tuple[float, int]] = []
        self._riff_times: list[float] = []
        self._riff_idx = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(T.PAD_H, T.PAD_V, T.PAD_H, T.PAD_V)
        root.setSpacing(10)

        # ── 상단 바 ──
        top = QHBoxLayout()
        self.link_btn = QPushButton("← 링크")
        self.score_btn = QPushButton("← 악보")
        for b in (self.link_btn, self.score_btn):
            b.setStyleSheet(T.qss_ghost_btn())
        self.link_btn.clicked.connect(self.backToLinkRequested.emit)
        self.score_btn.clicked.connect(self.backToScoreRequested.emit)
        top.addWidget(self.link_btn)
        top.addWidget(self.score_btn)
        top.addSpacing(10)
        self.song_lbl = QLabel("—")
        self.song_lbl.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS}';"
            "font-size:15px;font-weight:700;")
        top.addWidget(self.song_lbl)
        top.addStretch(1)
        self.bpm_lbl = QLabel("")
        self.bpm_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;")
        top.addWidget(self.bpm_lbl)
        root.addLayout(top)

        # ── 다음 진행 미리보기: 건반(현재 스케일) 바로 위 — 좌=왼손 / 우=오른손 ──
        #    바뀌는 박(구간 경계)에 위에서 내려오며 교체(SlideGuide).
        #    배치는 아래 피아노 직전에서 root에 추가.
        cap_qss = f"color:{T.TEXT_MUTED};font-size:11px;"
        prev_row = QHBoxLayout()
        lcol = QVBoxLayout(); lcol.setSpacing(2)
        lcap = QLabel("다음 ▸ 왼손(코드톤)")
        lcap.setStyleSheet(cap_qss)
        lcol.addWidget(lcap)
        self.next_l = SlideGuide()
        lcol.addWidget(self.next_l)
        prev_row.addLayout(lcol)
        prev_row.addStretch(1)
        rcol = QVBoxLayout(); rcol.setSpacing(2)
        rcap = QLabel("다음 ▸ 오른손(스케일)")
        rcap.setStyleSheet(cap_qss)
        rcap.setAlignment(Qt.AlignmentFlag.AlignRight)
        rcol.addWidget(rcap)
        self.next_r = SlideGuide()
        rcol.addWidget(self.next_r, alignment=Qt.AlignmentFlag.AlignRight)
        prev_row.addLayout(rcol)
        self._prev_wrap = QWidget()
        self._prev_wrap.setLayout(prev_row)

        # ── 코드 HUD: 좌=현재 / 우=다음(텍스트+카운트인) — 재생바 바로 위 배치 ──
        hud = QFrame()
        hud.setStyleSheet(
            f"QFrame{{background:{T.BG_INSET};border:1px solid {T.BORDER_SUBTLE};"
            f"border-radius:12px;}}")
        hl = QHBoxLayout(hud); hl.setContentsMargins(18, 12, 18, 12); hl.setSpacing(18)
        # 현재
        cur = QVBoxLayout(); cur.setSpacing(2)
        self.chord_lbl = QLabel("—")
        self.chord_lbl.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-family:'{T.FONT_SANS_EN}';"
            "font-size:28px;font-weight:900;border:none;")
        cur.addWidget(self.chord_lbl)
        self.scale_lbl = QLabel("")
        self.scale_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';"
            "font-size:15px;font-weight:700;border:none;letter-spacing:1px;")
        cur.addWidget(self.scale_lbl)
        self.acc_lbl = QLabel("")          # 실시간 적중률 배지(존별, §7.5)
        self.acc_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';"
            "font-size:12px;border:none;")
        cur.addWidget(self.acc_lbl)
        cur.addStretch(1)
        hl.addLayout(cur)
        # 가운데 빈칸: 리프연습 시 리프 가이드(현재↔다음 사이). OFF면 빈 공간.
        hl.addStretch(1)
        self.riff = RiffView()
        self.riff.setVisible(False)
        hl.addWidget(self.riff, 6)
        hl.addStretch(1)
        # 다음 (텍스트 + 미니 가이드 + 카운트인)
        nxt = QVBoxLayout(); nxt.setSpacing(4)
        self.next_lbl = QLabel("")
        self.next_lbl.setStyleSheet(
            f"color:{T.TEXT_MUTED};font-family:'{T.FONT_MONO}';font-size:12px;border:none;")
        self.next_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        nxt.addWidget(self.next_lbl)
        self.countin = CountIn()
        self.countin.setFixedWidth(250)
        nxt.addWidget(self.countin)
        hl.addLayout(nxt)
        self._hud = hud          # 배치는 아래 스크럽 직전에서 root에 추가

        # ── 리프연습 토글 + 난이도/루프 — 제일 위(상단바 바로 아래) ──
        rrow = QHBoxLayout()
        self.riff_btn = QPushButton("리프연습")
        self.riff_btn.setCheckable(True)
        self.riff_btn.setFixedSize(150, 40)   # ON/OFF 토글해도 크기 불변(레이아웃 고정)
        self.riff_btn.clicked.connect(self._toggle_riff)
        rrow.addWidget(self.riff_btn)
        rrow.addSpacing(10)
        # 난이도 선택기(§7.5, 가이드 모드 전용) — 통과/실패 없음, 채점 기준 필터
        self.diff_combo = QComboBox()
        self.diff_combo.addItems([
            "난이도 없음", "Lv1 · 근음+코드톤", "Lv2 · 근음+스케일", "Lv3 · 코드톤+스케일"])
        self.diff_combo.setFixedHeight(40)
        self.diff_combo.setStyleSheet(
            f"QComboBox{{background:transparent;color:{T.TEXT_PRIMARY};"
            f"border:1px solid {T.BORDER_ACTIVE};border-radius:10px;"
            "padding:4px 12px;font-size:13px;font-weight:700;}"
            f"QComboBox QAbstractItemView{{background:{T.BG_INSET};"
            f"color:{T.TEXT_BODY};selection-background-color:{T.BORDER_DEFAULT};}}")
        self.diff_combo.currentIndexChanged.connect(self._on_level_changed)
        rrow.addWidget(self.diff_combo)
        # 루프 버튼 — 사이드바 토글(생성한 루프 리스트, 루프별 ON/OFF)
        self.loop_btn = QPushButton("루프 ▸")
        self.loop_btn.setCheckable(True)
        self.loop_btn.setFixedHeight(40)
        self.loop_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{T.TEXT_PRIMARY};"
            f"border:1px solid {T.BORDER_ACTIVE};border-radius:10px;"
            "padding:4px 18px;font-size:13px;font-weight:700;}"
            f"QPushButton:checked{{background:{T.WHITE};color:{T.BG_BASE};}}")
        self.loop_btn.clicked.connect(self._toggle_loop_panel)
        rrow.addWidget(self.loop_btn)
        rrow.addStretch(1)
        root.addLayout(rrow)
        self._style_riff_btn()

        # ── 다음 미리보기 → 피아노(현재 스케일) 순서로 쌓기 ──
        root.addWidget(self._prev_wrap)
        # ── 피아노 (리프연습과 무관하게 가만히 — 가이드 그대로) ──
        self.piano = PianoWidget()
        # 화면 건반은 항상 오른손(솔로) 존으로 채점(§7.5)
        self.piano.notePlayed.connect(
            lambda midi, on: self.on_midi_note(midi, on, screen=True))
        root.addWidget(self.piano, 1)

        # ── 코드박스(HUD) — 재생바 바로 위 ──
        root.addWidget(hud)

        # ── 스크럽 ──
        self.scrub = ScrubBar()
        self.scrub.seekRequested.connect(self._on_seek)
        root.addWidget(self.scrub)

        # ── 재생/일시정지 (흰 원형, §6.1) ──
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedSize(60, 60)
        self.play_btn.setStyleSheet(
            f"QPushButton{{background:{T.WHITE};color:{T.BG_BASE};border:none;"
            f"border-radius:30px;font-size:22px;font-weight:700;}}"
            f"QPushButton:hover{{background:{T.TEXT_BODY};}}")
        self.play_btn.clicked.connect(self._toggle_play)
        bottom.addWidget(self.play_btn)
        bottom.addStretch(1)
        root.addLayout(bottom)

        # ── 패스 요약 카드 (오버레이, §7.5) ──
        self.pass_card = PassCard(self)

        # ── 루프 사이드바 (오버레이) — 생성한 루프 리스트 + 루프별 ON/OFF ──
        self.loop_panel = QFrame(self)
        self.loop_panel.hide()
        self.loop_panel.setStyleSheet(
            f"QFrame{{background:{T.BG_SURFACE};border:1px solid {T.BORDER_DEFAULT};"
            "border-radius:12px;}")
        pv = QVBoxLayout(self.loop_panel)
        pv.setContentsMargins(16, 14, 16, 14)
        pv.setSpacing(6)
        panel_title = QLabel("루프")
        panel_title.setStyleSheet(
            f"color:{T.TEXT_PRIMARY};font-size:14px;font-weight:700;border:none;")
        pv.addWidget(panel_title)
        self.loop_rows = QVBoxLayout()
        self.loop_rows.setSpacing(4)
        pv.addLayout(self.loop_rows)
        pv.addStretch(1)

    def showEvent(self, e):
        super().showEvent(e)
        stagger([self._prev_wrap, self.piano, self._hud, self.scrub, self.play_btn])

    # ── 리프연습 토글 버튼 스타일 ────────────────────────────────
    def _style_riff_btn(self):
        on = (self._mode == "practice")
        self.riff_btn.setChecked(on)
        self.riff_btn.setText("리프연습  ●  ON" if on else "리프연습  ○  OFF")
        # 두 상태 동일 박스 모델(테두리 1px·폰트 동일) + 고정 크기 → 토글해도 안 밀림
        if on:
            bg, fg, border = T.WHITE, T.BG_BASE, T.WHITE
        else:
            bg, fg, border = "transparent", T.TEXT_PRIMARY, T.BORDER_ACTIVE
        self.riff_btn.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};border:1px solid {border};"
            f"border-radius:10px;font-size:13px;font-weight:700;}}")

    # ── 루프 사이드바(§6): 루프별 ON/OFF ─────────────────────────
    def _toggle_loop_panel(self):
        if self.loop_btn.isChecked():
            self._build_loop_rows()
            self._place_loop_panel()
            self.loop_panel.show()
            self.loop_panel.raise_()
        else:
            self.loop_panel.hide()

    def _place_loop_panel(self):
        w = 270
        self.loop_panel.setGeometry(self.width() - w - 20, 64,
                                    w, min(380, self.height() - 130))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.loop_panel.isVisible():
            self._place_loop_panel()

    def _build_loop_rows(self):
        while self.loop_rows.count():
            it = self.loop_rows.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        loops = getattr(self.tl, "loops", []) if self.tl else []
        if not loops:
            lbl = QLabel("박자 조정 화면의 코드표에서\n루프를 만들 수 있어요.")
            lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;border:none;")
            self.loop_rows.addWidget(lbl)
            return
        for lp in loops:
            row = QWidget()
            row.setStyleSheet("border:none;")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            name = QLabel(f"{lp['name']}  {lp['start_bar'] + 1}–{lp['end_bar'] + 1}마디")
            name.setStyleSheet(f"color:{T.TEXT_BODY};font-size:12px;border:none;")
            h.addWidget(name, 1)
            btn = QPushButton("● ON" if lp.get("on") else "○ OFF")
            btn.setCheckable(True)
            btn.setChecked(bool(lp.get("on")))
            btn.setFixedWidth(66)
            btn.setStyleSheet(T.qss_ghost_btn())
            btn.toggled.connect(lambda on, l=lp, b=btn: self._toggle_loop(l, b, on))
            h.addWidget(btn)
            self.loop_rows.addWidget(row)

    @staticmethod
    def _toggle_loop(lp: dict, btn: QPushButton, on: bool):
        lp["on"] = on
        btn.setText("● ON" if on else "○ OFF")

    def _loop_spans(self) -> list[tuple[float, float]]:
        """켜진 사용자 루프의 (start_sec, end_sec) — 채점 마디 격자 기준."""
        loops = getattr(self.tl, "loops", []) if self.tl else []
        if not loops:
            return []
        bars = self.scorer._bars if self.scorer else self.tl.bar_times
        n = len(bars) - 1
        out = []
        for lp in loops:
            if not lp.get("on"):
                continue
            s, e = lp["start_bar"], lp["end_bar"] + 1
            if 0 <= s < e <= n:
                out.append((bars[s], bars[e]))
        return out

    # ── 난이도(§7.5) ─────────────────────────────────────────────
    def _on_level_changed(self, lv: int):
        if self.scorer:
            self.scorer.set_level(lv)          # 기준 교체 = 진행 중 패스 무효화
        self.acc_lbl.setText("")
        self._apply_targets()

    def _apply_targets(self):
        """현재 구간의 존별 목표음을 건반 배지 필터로 반영(비목표음 흐리게)."""
        seg = self._current_segment()
        if seg is None or not self.scorer or self.scorer.level == 0:
            self.piano.set_targets(0)
            return
        self.piano.set_targets(self.tl.split_point,
                               self.scorer.left_targets(seg),
                               self.scorer.right_targets(seg))

    # ── ML 예시 재생 ─────────────────────────────────────────────
    def _current_segment(self):
        if not self.tl or self.playhead is None:
            return None
        return self.tl.segment_at(self.playhead.position_sec())

    # ── 리프를 재생에 함께 굽기(재생 헤드 동기) ──────────────────
    def _build_riff_events(self):
        """모든 구간의 리프 음을 (절대초, midi)로 펼쳐 정렬. 곡 타임라인에 '구워' 둔다.

        재생 헤드 위치에 맞춰 트리거하므로 일시정지·시킹 시 함께 멈추고 따라간다(§2).
        """
        ev: list[tuple[float, int]] = []
        if self.tl:
            beat = self.tl.beat_sec()
            for seg in self.tl.segments:
                for n in seg.example:
                    ev.append((seg.start_sec + n["beat_pos"] * beat, n["midi"]))
            ev.sort(key=lambda e: e[0])
        self._riff_events = ev
        self._riff_times = [t for t, _ in ev]
        if self.scorer:
            self.scorer.set_riff_events(ev)   # 리프 일치도 채점(§7.5 2차)

    def _seek_riff_idx(self, sec: float):
        """리프 재생 커서를 sec 위치로 이동(시킹/모드 진입 시 과거 음 몰아 재생 방지)."""
        self._riff_idx = bisect.bisect_left(self._riff_times, sec)

    # ── 타임라인 로드 ────────────────────────────────────────────
    def set_timeline(self, tl: Timeline):
        if self.playhead:
            self.playhead.pause()
        self.tl = tl
        self._last_idx = -1
        self.scorer = ScoreEngine(tl)      # 보정(악보 화면) 반영해 패스 창 재계산
        self.scorer.set_level(self.diff_combo.currentIndex())
        self.scorer.set_mode(self._mode)
        self._build_loop_rows()            # 사용자 루프 리스트(사이드바) 갱신
        self.acc_lbl.setText("")
        self.pass_card.hide()
        if not getattr(tl, "scale_riffs", None):   # 아직이면 1회 굽기(§8)
            bake_examples(tl, self._ml_model)
        self._build_riff_events()          # 리프를 곡에 함께 구움(§2)
        self._riff_idx = 0
        self.playhead = Playhead(tl.content_end(), tl.audio_ref, self)
        self.playhead.positionChanged.connect(self._on_tick)
        self.playhead.stateChanged.connect(self._on_state)

        self.song_lbl.setText(tl.title or tl.audio_ref or "내 곡")
        self.bpm_lbl.setText(f"{tl.key}  ·  {tl.bpm:.0f} BPM")
        self.scrub.set_timeline(tl)
        self.scrub.set_position(0.0)
        self._render_at(0.0)

    def pause(self):
        if self.playhead:
            self.playhead.pause()

    # ── 리프연습 ON/OFF ──────────────────────────────────────────
    def _toggle_riff(self):
        self._mode = "practice" if self._mode != "practice" else "guide"
        self._style_riff_btn()
        practice = (self._mode == "practice")
        self.riff.setVisible(practice)
        # 리프연습은 난이도 미적용(§7) — 선택기 비활성(루프는 모드 무관)
        self.diff_combo.setEnabled(not practice)
        # 모드 전환 = 채점 기준 교체 + 진행 중 패스 무효화(§7: 기준은 모드를 따라감)
        if self.scorer:
            self.scorer.set_mode(self._mode)
        self.acc_lbl.setText("")
        if practice:
            seg = self._current_segment()
            if seg and self.tl:
                self.riff.set_segment(seg, self.tl.bpm, self.tl.time_sig_beats())
            # 현재 위치부터 리프 재생(과거 음은 건너뜀)
            self._build_riff_events()
            self._seek_riff_idx(self.playhead.position_sec() if self.playhead else 0.0)
        else:
            self.riff.clear()

    # ── 재생 제어 ────────────────────────────────────────────────
    def _toggle_play(self):
        if self.playhead:
            self.playhead.toggle()

    def _on_state(self, playing: bool):
        self.play_btn.setText("⏸" if playing else "▶")

    def _on_seek(self, sec: float):
        if self.scorer:
            self.scorer.on_seek(sec)   # seek이 동기로 tick을 부를 수 있어 먼저 무효화
        self.acc_lbl.setText("")
        if self.playhead:
            self.playhead.seek(sec)
            self._render_at(sec)
            self._seek_riff_idx(sec)        # 리프 커서도 함께 점프

    def _on_tick(self, sec: float):
        self.scrub.set_position(sec)
        # 채점(§7.5): 패스 경계 감지 → 요약(기준은 모드를 따라감)
        if self.scorer:
            summary = self.scorer.tick(sec)
            if summary:
                self._on_pass_done(summary)
        # 사용자 루프(§6): 켜진 루프 끝에 닿으면 시작으로 — 채점 tick 뒤에 되감기
        if self.playhead and self.playhead.is_playing():
            for s0, e0 in self._loop_spans():
                if e0 <= sec < e0 + 0.5:
                    self._on_seek(s0)
                    return
        self._render_at(sec + SYNC_LOOKAHEAD_SEC)   # 구간 변경 시 무거운 갱신
        self._update_live(sec)                       # 매 틱 카운트인·리프 헤드
        # 리프를 재생 헤드에 맞춰 트리거(재생 중일 때만 → 일시정지 시 함께 멈춤, §2)
        if self._mode == "practice" and self.playhead and self.playhead.is_playing():
            ev = self._riff_events
            while self._riff_idx < len(ev) and ev[self._riff_idx][0] <= sec:
                self.note_player.play_note(ev[self._riff_idx][1])
                self._riff_idx += 1

    # ── 상태 → UI 렌더 (구간 변경 시) ────────────────────────────
    def _render_at(self, sec: float):
        if not self.tl or not self.tl.segments:
            return
        idx = self.tl.segment_index_at(sec)
        if idx < 0 or idx == self._last_idx:
            return
        self._last_idx = idx
        seg = self.tl.segments[idx]
        self.piano.set_scale(seg.note_set, seg.chord_tones())
        self.piano.set_degrees(
            {pc: degree_number(pc, seg.scale_root) for pc in seg.note_set})
        self.piano.set_pressed(set())
        self._apply_targets()              # 난이도 목표음 필터(구간별, §7.5)
        self._update_hud(seg)
        # 리프연습: 새 구간 진입 시 리프 뷰만 갱신(재생은 _on_tick이 헤드 동기로 트리거)
        if self._mode == "practice":
            self.riff.set_segment(seg, self.tl.bpm, self.tl.time_sig_beats())

    def _update_hud(self, seg):
        self.chord_lbl.setText(seg.chord.name)
        self.scale_lbl.setText(seg.scale_name)
        nxt = self.tl.next_segment(seg)
        if nxt:
            self.next_lbl.setText(f"다음 ▸  {nxt.chord.name}   {nxt.scale_name}")
            # 왼손 = 다음 코드의 코드톤만 / 오른손 = 다음 스케일 전체
            ct = nxt.chord_tones()
            self.next_l.set_scale(ct, ct, nxt.chord.root)
            self.next_r.set_scale(nxt.note_set, ct, nxt.scale_root)
        else:
            self.next_lbl.setText("")
            self.next_l.clear()
            self.next_r.clear()

    # ── 매 틱 라이브 갱신: 카운트인 + 리프 헤드 ──────────────────
    def _update_live(self, sec: float):
        if not self.tl or not self.tl.segments:
            return
        idx = self.tl.segment_index_at(sec)
        if idx < 0:
            return
        seg = self.tl.segments[idx]
        nxt = self.tl.next_segment(seg)
        if nxt is None:
            self.countin.set_remaining(None)
        else:
            beat = self.tl.beat_sec()
            self.countin.set_remaining((seg.end_sec - sec) / beat if beat else None)
        if self._mode == "practice" and self.playhead and self.playhead.is_playing():
            self.riff.set_play_pos_sec(sec, seg.start_sec, self.tl.bpm)

    # ── 채점 표시 ────────────────────────────────────────────────
    def _on_pass_done(self, summary):
        # 추이는 가이드 존별 적중률만(§7.5 1차) — 리프연습 요약엔 미표기
        trend = self.scorer.trend if self._mode == "guide" else []
        self.pass_card.show_summary(summary, trend)
        self.acc_lbl.setText("")           # 새 패스 시작 — 배지 리셋

    def _update_badge(self):
        s = self.scorer.cur
        r = s.right_pct()
        l = s.left_pct()
        if r is None and l is None:
            self.acc_lbl.setText("")
            return
        fmt = lambda p: "–" if p is None else f"{p}%"
        self.acc_lbl.setText(f"오른손 {fmt(r)} · 왼손 {fmt(l)}")

    # ── 입력 콜백 ────────────────────────────────────────────────
    def on_midi_note(self, midi: int, is_on: bool, screen: bool = False):
        if not self.tl or self.playhead is None:
            return
        pressed = set(self.piano._pressed)
        if is_on:
            pressed.add(midi)
            self.note_player.play_note(midi)
        else:
            pressed.discard(midi)
        self.piano.set_pressed(pressed)
        # 채점: 재생 중 note-on만(§7.5 — 정지 중 자유 연주는 무채점)
        if is_on and self.scorer and self.playhead.is_playing():
            self.scorer.note_on(midi, self.playhead.position_sec(), screen=screen)
            if self._mode == "guide":      # 실시간 배지는 존별 채점만
                self._update_badge()
