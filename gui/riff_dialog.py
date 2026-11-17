"""리프 생성 창 — 곡 처음부터 끝까지 4마디마다 1마디 리프 1개(곡 스케일, 리프당 5~6음).

블록의 마디 차례 = [프로그램, 나, 프로그램, 나] — 같은 리프를 같은 음 그대로 주고받는다.
착지 섞기 체크(3도·7도) = 블록이 기본 → 3도 → 7도 리프 순으로 돈다(켠 것만). 목표음이 스케일에 없는 코드는 코드톤 착지.
목록 클릭 = 그 블록 리프를 롤에 표시, 듣기 = 선택 리프를 원곡 템포로 재생,
다시 만들기 = 선택 리프만 다른 변주, 확정 = 블록마다 기록(프로그램 마디 음은 call 표시), 취소 = 이전 리프 복원.
"""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
                             QCheckBox)

from ml.generate import bake_progression, riff_blocks, shift_riff, write_examples, RIFF_NOTES, _landing_pc
from gui import theme as T
from gui.widgets.riff_roll import RiffRoll
from player.note_synth import shared_player

GOAL_KR = {"third": "3도", "seventh": "7도"}
LANDING_GOALS = ("third", "seventh")   # 순환 순서: 기본 → 3도 → 7도


def landing_goals(tl) -> list:
    """리프모드에서 켠 착지 섞기 목표들(tl.practice["landing"])."""
    goals = tl.practice.get("landing")
    return [g for g in LANDING_GOALS if isinstance(goals, list) and g in goals]


def block_goal(goals, i: int):
    """i번째 블록의 착지 목표 — [기본, 켠 목표들...]을 순환. None = 기본 리프."""
    cycle = [None] + [g for g in LANDING_GOALS if g in goals]
    return cycle[i % len(cycle)]


class RiffDialog(QDialog):
    def __init__(self, tl, model, parent=None):
        super().__init__(parent)
        self.setWindowTitle("리프 생성")
        self.setStyleSheet(f"QDialog{{background:{T.BG_BASE};}}")
        self.setMinimumWidth(640)
        self.tl, self.model = tl, model
        self.skip = bool(tl.practice.get("skip_detour"))   # 키 밖 코드 제외 → 그 마디엔 리프 없음
        self.blocks = riff_blocks(tl, self.skip)
        self.riffs: list[dict] = []   # 블록 순서대로 {variant, notes, start_sec(프로그램 마디 시작)}
        self._play_id = 0
        self.note_player = shared_player()
        self._saved = [list(seg.example) for seg in tl.segments]
        lay = QVBoxLayout(self)
        scale = tl.practice.get("scale", {}).get("name", "")
        self.info = QLabel(f"{scale} · 리프당 {RIFF_NOTES[0]}~{RIFF_NOTES[1]}음")
        self.info.setStyleSheet(f"color:{T.TEXT_BODY};font-size:13px;")
        lay.addWidget(self.info)
        checks = QHBoxLayout()
        self.landing_chks = {}
        saved = landing_goals(tl)
        segs = [s for s in tl.segments if not (self.skip and s.is_detour)]
        for goal in LANDING_GOALS:
            chk = QCheckBox(f"{GOAL_KR[goal]} 착지 섞기")
            chk.setStyleSheet(f"QCheckBox{{color:{T.TEXT_BODY};font-size:13px;}}")
            ok = any(_landing_pc(s, goal) is not None for s in segs)   # 안 되는 코드는 코드톤 착지
            chk.setEnabled(ok)
            chk.setToolTip("" if ok else f"이 스케일엔 어떤 코드의 {GOAL_KR[goal]} 음도 없어요")
            chk.setChecked(ok and goal in saved)
            chk.toggled.connect(self.make_riffs)
            checks.addWidget(chk)
            self.landing_chks[goal] = chk
        checks.addStretch(1)
        lay.addLayout(checks)
        self.need_lbl = QLabel(f"4마디마다 1마디 리프를 프로그램·나·프로그램·나로 주고받아요 → 리프 {len(self.blocks)}개")
        self.need_lbl.setStyleSheet(f"color:{T.TEXT_MUTED};font-size:12px;")
        lay.addWidget(self.need_lbl)
        self.list = QListWidget()
        self.list.setFixedHeight(110)
        self.list.setStyleSheet(
            f"QListWidget{{background:{T.BG_INSET};color:{T.TEXT_BODY};"
            f"border:1px solid {T.BORDER_SUBTLE};border-radius:6px;}}"
            f"QListWidget::item:selected{{background:{T.BG_SURFACE_ALT};color:{T.TEXT_PRIMARY};}}")
        self.list.currentRowChanged.connect(self._show)
        lay.addWidget(self.list)
        self.roll = RiffRoll()
        lay.addWidget(self.roll)
        row = QHBoxLayout()
        self.listen_btn = QPushButton("듣기 ▶")
        self.listen_btn.setStyleSheet(T.qss_ghost_btn())
        self.listen_btn.clicked.connect(self.toggle_listen)
        row.addWidget(self.listen_btn)
        row.addStretch(1)
        self.regen_btn = QPushButton("다시 만들기")
        self.cancel_btn = QPushButton("취소")
        self.ok_btn = QPushButton("확정 ▶")
        for btn in (self.regen_btn, self.cancel_btn):
            btn.setStyleSheet(T.qss_ghost_btn())
            row.addWidget(btn)
        self.ok_btn.setStyleSheet(T.qss_primary_btn())
        row.addWidget(self.ok_btn)
        lay.addLayout(row)
        self.regen_btn.clicked.connect(self.regenerate)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.accept)
        self.make_riffs()

    def _goals(self) -> list:
        return [g for g, chk in self.landing_chks.items() if chk.isChecked()]

    def _goal(self, i: int):
        return block_goal(self._goals(), i)

    def _bake(self, i: int, variant: int) -> dict:
        block = self.blocks[i]
        a, b = block["bars"][0]
        b0 = self.tl.beat_at(a)
        res = bake_progression(self.tl, self.model, a, b, self._goal(i), variant,
                               count=RIFF_NOTES, allowed=block["allowed"],
                               repeats=[self.tl.beat_at(x) - b0 for x, _ in block["bars"][1:]])
        return {"notes": res["notes"]}

    def make_riffs(self, *_):
        """블록마다 프로그램 마디(첫 마디)에서 리프 1개를 굽는다. 착지음 체크를 바꿔도 다시 굽는다."""
        self.stop_listen()
        self.riffs = [{"variant": 0, **self._bake(i, 0)} for i in range(len(self.blocks))]
        self.list.clear()
        for i, block in enumerate(self.blocks):
            goal = self._goal(i)
            self.list.addItem(block["label"] + (f" · {GOAL_KR[goal]} 착지" if goal else ""))
        if self.riffs:
            self.list.setCurrentRow(0)
            self._show(0)

    def _show(self, row: int):
        self.stop_listen()
        if not 0 <= row < len(self.riffs):
            return
        r = self.riffs[row]
        a, b = self.blocks[row]["bars"][0]
        b0 = self.tl.beat_at(a)
        notes = [{"midi": n["midi"], "beat_pos": self.tl.beat_at(n["start_sec"]) - b0,
                  "dur_beats": self.tl.beats_between(n["start_sec"], n["start_sec"] + n["duration_sec"])}
                 for n in r["notes"]]
        self.note_player.preload({n["midi"] for n in r["notes"]})
        scale = self.tl.practice.get("scale") or {}
        chords = [(max(self.tl.beat_at(s.start_sec) - b0, 0.0), self.tl.beat_at(min(s.end_sec, b)) - b0,
                   s.chord_tones(), s.chord.root % 12, s.chord.name)
                  for s in self.tl.segments if s.start_sec < b and s.end_sec > a]
        self.roll.set_riff(notes, scale.get("note_set", []), chords, self.tl.time_sig_beats(), 1,
                           scale.get("root", 0))

    def toggle_listen(self):
        if self._play_id % 2:
            self.stop_listen()
            return
        row = self.list.currentRow()
        if not 0 <= row < len(self.riffs):
            return
        self._play_id += 1   # 홀수 = 재생 중; 바뀌면 남은 타이머는 무시된다
        pid = self._play_id
        t0, t1 = self.blocks[row]["bars"][0]
        self.note_player.warmup()
        for n in self.riffs[row]["notes"]:
            QTimer.singleShot(max(0, round((n["start_sec"] - t0) * 1000)),
                              lambda n=n: pid == self._play_id and self.note_player.play_note(
                                  n["midi"], n["duration_sec"]))
        QTimer.singleShot(round((t1 - t0) * 1000),
                          lambda: pid == self._play_id and self.stop_listen())
        self.listen_btn.setText("정지 ■")

    def stop_listen(self):
        if self._play_id % 2:
            self._play_id += 1
            self.note_player.stop_all()
        self.listen_btn.setText("듣기 ▶")

    def regenerate(self):
        row = self.list.currentRow()
        if not 0 <= row < len(self.riffs):
            return
        r = self.riffs[row]
        r["variant"] += 1
        r.update(self._bake(row, r["variant"]))
        self._show(row)

    def _apply(self):
        """기존 리프를 지우고 블록마다 [프로그램, 나, 프로그램, 나] 마디에 같은 리프를 기록."""
        self.tl.practice["landing"] = self._goals()
        for seg in self.tl.segments:
            seg.example = []
        for block, r in zip(self.blocks, self.riffs):
            src = block["bars"][0][0]
            for k, (a, b) in enumerate(block["bars"]):
                notes = [{**n, "call": k % 2 == 0} for n in shift_riff(self.tl, r["notes"], src, a)]
                write_examples(self.tl, a, b, notes)
        for seg in self.tl.segments:
            if self.skip and seg.is_detour:
                seg.example = []

    def done(self, result):
        self.stop_listen()
        if result == QDialog.DialogCode.Accepted:
            self._apply()
        else:
            for seg, ex in zip(self.tl.segments, self._saved):
                seg.example = ex
        super().done(result)
