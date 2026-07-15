"""연주 채점 엔진 (정의서 §7.5) — 존 판정 + 패스 집계. Qt 비의존(테스트 가능).

- 존: 스플릿 미만 = 왼손(코드톤 판정) / 이상·화면건반 = 오른손(스케일 판정)
- 패스: 루프 1주기(사용자 override 반영). 미검출 시 곡 전체 = 1패스
- 유효 패스: 창 시작 ENTRY_TOL_SEC 이내 진입한 경우만(스크럽 진입 배제)
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from player.timeline import Timeline

LANDING_BEATS = 0.25   # 코드톤 착지 판정 폭(±박)
ENTRY_TOL_SEC = 0.3    # 이내로 패스 시작에 진입해야 유효 패스
RIFF_TOL_BEATS = 0.25  # 리프 일치 타이밍 허용창(±박, 리프연습 §7.5 2차)


@dataclass
class PassSummary:
    number: int = 0                 # 세션 내 완료 순번(1부터)
    right_hits: int = 0             # 오른손 스케일 적중
    right_total: int = 0
    left_hits: int = 0              # 왼손 코드톤 적중
    left_total: int = 0
    landing_hits: int = 0           # 코드톤 착지(마디당 1회)
    landing_opps: int = 0           # = 패스 마디 수
    out_counts: dict = field(default_factory=dict)   # {pc: 횟수} 스케일 밖
    riff_hits: int = 0              # 리프 일치(리프연습 모드)
    riff_total: int = 0             # = 패스 안 리프 음 수

    def right_pct(self) -> int | None:
        return round(100 * self.right_hits / self.right_total) if self.right_total else None

    def left_pct(self) -> int | None:
        return round(100 * self.left_hits / self.left_total) if self.left_total else None

    def riff_pct(self) -> int | None:
        return round(100 * self.riff_hits / self.riff_total) if self.riff_total else None

    def top_out_pc(self) -> int | None:
        return max(self.out_counts, key=self.out_counts.get) if self.out_counts else None


class ScoreEngine:
    def __init__(self, tl: Timeline):
        self.tl = tl
        self.trend: list[int] = []      # 완료 패스 오른손 적중률 %(세션 내, 가이드)
        self.mode = "guide"             # guide=존별 / practice=리프 일치도(§7.5)
        self._riff: list[tuple[float, int]] = []   # (절대초, midi) 정렬
        self._bars = self._build_bars()
        self._pass_no = 0
        self.rebuild()
        self.set_level(0)

    def set_mode(self, mode: str):
        """guide ↔ practice — 채점 기준이 모드를 따라감(§7). 진행 중 패스 무효화."""
        self.mode = mode
        self.on_seek(0.0)

    def set_riff_events(self, events):
        """리프연습 일치도용 (절대초, midi) 목록 — 플레이어가 구운 것을 그대로 받음."""
        self._riff = sorted(events)
        self.on_seek(0.0)

    def set_level(self, lv: int):
        """난이도(§7.5) — 존별 채점 기준 교체. 0=없음(상시 기본=Lv3 기준).

        기준이 바뀌면 진행 중 패스는 혼합 집계가 되므로 무효화한다.
        """
        root = lambda seg: {seg.chord.root % 12}
        chord = lambda seg: set(seg.chord_tones())
        scale = lambda seg: set(seg.note_set)
        self.level = lv
        self.left_targets, self.right_targets = {
            0: (chord, scale),          # 상시 기본
            1: (root, chord),           # Lv1: 왼손 근음 + 오른손 코드톤
            2: (root, scale),           # Lv2: 왼손 근음 + 오른손 스케일
            3: (chord, scale),          # Lv3: 왼손 코드톤 + 오른손 스케일
        }[lv]
        self.on_seek(0.0)

    def _build_bars(self) -> list[float]:
        if len(self.tl.bar_times) >= 2:
            return list(self.tl.bar_times)
        # 구 캐시 JSON 폴백: bpm 균등 격자
        bar_len = self.tl.beat_sec() * self.tl.time_sig_beats()
        cs, ce = self.tl.content_span
        if ce <= cs:
            cs, ce = 0.0, self.tl.total_sec()
        if bar_len <= 0 or ce <= cs:
            return []
        bars = []
        t = cs
        while t < ce - 1e-6:
            bars.append(t)
            t += bar_len
        bars.append(ce)
        return bars

    def rebuild(self):
        """패스 창 재계산(루프 override 반영) + 진행 중 패스 리셋."""
        bars = self._bars
        n = len(bars) - 1               # 마디 수
        if self.tl.loop_override:
            L, phase = self.tl.loop_override, 0   # override 시 감지 위상 무의미
        else:
            L, phase = self.tl.loop_len, self.tl.loop_phase
        # (start_sec, end_sec, start_bar, n_bars)
        if n < 1:
            self.windows: list[tuple[float, float, int, int]] = []
        elif L <= 0 or L >= n:
            self.windows = [(bars[0], bars[n], 0, n)]
        else:
            self.windows = []
            b = phase
            while b + L <= n:
                self.windows.append((bars[b], bars[b + L], b, L))
                b += L
            if not self.windows:
                self.windows = [(bars[0], bars[n], 0, n)]
        self._cur_idx: int | None = None
        self._valid = False
        self._reset_cur()

    def _reset_cur(self):
        self.cur = PassSummary()
        self._landed: set[int] = set()  # 착지 인정된 마디 인덱스
        self._riff_matched: set[int] = set()  # 일치 처리된 리프 이벤트 인덱스

    def _window_at(self, sec: float) -> int | None:
        for i, w in enumerate(self.windows):
            if w[0] <= sec < w[1]:
                return i
        return None

    def window_span(self, sec: float) -> tuple[float, float] | None:
        """sec가 속한 패스 창 (start, end) — 루프 재생용."""
        i = self._window_at(sec)
        return self.windows[i][:2] if i is not None else None

    # ── 입력 ────────────────────────────────────────────────────
    def note_on(self, midi: int, sec: float, screen: bool = False):
        if self.mode == "practice":     # 리프연습은 리프 일치도만(§7.5)
            self._match_riff(midi, sec)
            return
        seg = self.tl.segment_at(sec)
        if seg is None or not seg.note_set:
            return
        pc = midi % 12
        if screen or midi >= self.tl.split_point:   # 화면건반은 항상 오른손 존
            self.cur.right_total += 1
            if pc in self.right_targets(seg):
                self.cur.right_hits += 1
        else:
            self.cur.left_total += 1
            if pc in self.left_targets(seg):
                self.cur.left_hits += 1
        if pc not in seg.note_set:                  # "스케일 밖"(중립 표현, §7.5)
            self.cur.out_counts[pc] = self.cur.out_counts.get(pc, 0) + 1
        self._check_landing(pc, sec, seg)

    def _match_riff(self, midi: int, sec: float):
        """현재 패스 창 안의 미일치 리프 음 중 같은 음높이·허용창 내 최근접을 일치 처리."""
        if self._cur_idx is None or not self._riff:
            return
        w = self.windows[self._cur_idx]
        tol = RIFF_TOL_BEATS * self.tl.beat_sec()
        best = None
        for i in range(bisect.bisect_left(self._riff, (w[0],)), len(self._riff)):
            t, m = self._riff[i]
            if t >= w[1]:
                break
            if i in self._riff_matched or m != midi or abs(t - sec) > tol:
                continue
            if best is None or abs(t - sec) < abs(self._riff[best][0] - sec):
                best = i
        if best is not None:
            self._riff_matched.add(best)

    def _check_landing(self, pc: int, sec: float, seg):
        if self._cur_idx is None or pc not in seg.chord_tones():
            return
        bars = self._bars
        n = len(bars) - 1
        # 가장 가까운 마디 경계 인덱스
        j = bisect.bisect_left(bars, sec)
        if j == 0:
            i = 0
        elif j > n:
            i = n
        else:
            i = j if bars[j] - sec < sec - bars[j - 1] else j - 1
        w = self.windows[self._cur_idx]
        if not (w[2] <= i < w[2] + w[3]):           # 경계가 현재 패스 안의 마디여야
            return
        span = (bars[i + 1] - bars[i]) if i < n else (bars[i] - bars[i - 1])
        beat_len = span / self.tl.time_sig_beats()
        if abs(sec - bars[i]) <= LANDING_BEATS * beat_len:
            self._landed.add(i)

    # ── 재생 헤드 ───────────────────────────────────────────────
    def tick(self, sec: float) -> PassSummary | None:
        """패스 경계 감지. 유효 패스 완료 시 요약 반환."""
        idx = self._window_at(sec)
        if idx == self._cur_idx:
            return None
        out = None
        if self._cur_idx is not None and self._valid:
            w = self.windows[self._cur_idx]
            if sec >= w[1]:                          # 끝을 지나 자연 완료
                out = self._finalize(w)
        self._cur_idx = idx
        self._valid = idx is not None and (sec - self.windows[idx][0]) <= ENTRY_TOL_SEC
        self._reset_cur()
        return out

    def _finalize(self, w) -> PassSummary:
        s = self.cur
        if self.mode == "practice":
            s.riff_total = sum(1 for t, _ in self._riff if w[0] <= t < w[1])
            s.riff_hits = len(self._riff_matched)
        else:
            s.landing_hits = len(self._landed)
            s.landing_opps = w[3]
            if s.right_total:
                self.trend.append(s.right_pct())
        self._pass_no += 1
        s.number = self._pass_no
        return s

    def on_seek(self, sec: float):
        """스크럽/모드 전환 — 진행 중 패스 무효화. 다음 tick에서 재진입."""
        self._cur_idx = None
        self._valid = False
        self._reset_cur()
