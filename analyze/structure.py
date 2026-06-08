"""구조 분석 (브리프 §5.2) — 범위 한정: 길이 감지 + 턴 정렬만.

1. 마디 격자: BPM + 박자(기본 4/4) — 비트 시각을 마디로 묶음
2. 반복 단위(루프) 감지: 주기 후보 {1,2,4,8,16}, 마디별 코드 시퀀스 일치율,
   퍼지 매칭(끝 턴어라운드 허용), 임계값 ≈0.8 넘는 가장 짧은 주기 채택
3. 화성 리듬: 감지된 단위 안에서 코드 변경 빈도
※ 벌스/코러스 섹션 감지는 하지 않음(§5.2)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ingest.mir_extract import MirResult


@dataclass
class RawSegment:
    """코드 지속 구간(마디 정렬). 턴 분할 전 단위."""
    start_bar: int
    end_bar: int
    start_sec: float
    end_sec: float
    chord_name: str


@dataclass
class LoopInstance:
    start_bar: int
    end_bar: int


@dataclass
class StructureResult:
    beats_per_bar: int
    bar_times: list[float]          # 각 마디 시작 시각(+마지막 끝)
    per_bar_chord: list[str]        # 마디별 코드명
    segments: list[RawSegment] = field(default_factory=list)
    loop_len: int = 0               # 반복 단위(마디 수)
    harmonic_rhythm: float = 0.0    # 루프당 평균 코드 변경 수
    loop_phase: int = 0             # 루프 시작 마디 오프셋(인트로 보정)
    loop_instances: list[LoopInstance] = field(default_factory=list)  # 반복 위치
    is_loop_bar: list[bool] = field(default_factory=list)             # 마디별 루프 여부


LOOP_CANDIDATES = [1, 2, 4, 8, 16]
LOOP_THRESHOLD = 0.8
INSTANCE_THRESHOLD = 0.6   # 블록이 레퍼런스 패턴과 이 비율 이상 일치하면 루프 인스턴스


def _build_bar_grid(mir: MirResult, beats_per_bar: int) -> list[float]:
    """마디 시작 시각 리스트(+곡 끝). 다운비트에 앵커링(첫 다운비트 기준, t=0 가정 금지)."""
    duration = mir.duration
    dbs = [t for t in (mir.downbeat_times or []) if 0 <= t <= duration + 1e-3]
    if len(dbs) >= 2:
        bars = sorted(dbs)
        if bars[-1] < duration - 1e-3:
            bars = bars + [duration]
        return bars
    # 다운비트 부족 → 비트 격자 폴백(역시 첫 비트 기준, t=0 가정 안 함)
    bt = mir.beat_times
    if len(bt) >= beats_per_bar + 1:
        bars = list(bt[::beats_per_bar])
        if bars[-1] < duration:
            bars = bars + [duration]
        return bars
    start = bt[0] if bt else 0.0
    return [start, duration]


def _chord_for_bar(start: float, end: float, chords) -> str:
    """마디 구간을 가장 많이 덮는 코드명."""
    best, best_overlap = chords[0].name, -1.0
    for c in chords:
        ov = min(end, c.end_sec) - max(start, c.start_sec)
        if ov > best_overlap:
            best_overlap, best = ov, c.name
    return best


def _detect_loop(per_bar_chord: list[str]) -> int:
    n = len(per_bar_chord)
    if n <= 1:
        return max(1, n)
    for p in LOOP_CANDIDATES:
        if p > n // 2:
            break
        match, total = 0, 0
        for i in range(n - p):
            # 퍼지: 각 주기의 마지막 마디(턴어라운드)는 비교 제외
            if (i % p) == (p - 1):
                continue
            total += 1
            if per_bar_chord[i] == per_bar_chord[i + p]:
                match += 1
        rate = (match / total) if total else 0.0
        if rate >= LOOP_THRESHOLD:
            return p
    # 임계 못 넘으면 전체를 한 단위로
    return n


def _detect_loop_instances(per_bar_chord: list[str], loop_len: int):
    """루프 패턴을 슬라이드해 반복 위치(인스턴스)와 비루프 마디를 가린다(§5.2.4).

    반환: (phase, instances[LoopInstance], is_loop_bar[bool]).
    """
    n = len(per_bar_chord)
    is_loop = [False] * n
    if loop_len <= 0 or loop_len >= n:
        # 반복 미검출 → 전체를 한 인스턴스로(턴은 곡 전체에서 진행)
        return 0, [LoopInstance(0, n)], [True] * n

    # 최적 위상 오프셋: 각 오프셋에서 위치별 최빈 코드(레퍼런스) 대비 일치율 최대
    best_phase, best_rate, best_ref = 0, -1.0, None
    for o in range(loop_len):
        # 위치별 코드 모음
        cols = [[] for _ in range(loop_len)]
        b = o
        while b + loop_len <= n:
            for p in range(loop_len):
                cols[p].append(per_bar_chord[b + p])
            b += loop_len
        if not cols[0]:
            continue
        ref = [max(set(c), key=c.count) if c else None for c in cols]
        match = total = 0
        b = o
        while b + loop_len <= n:
            for p in range(loop_len):
                total += 1
                if per_bar_chord[b + p] == ref[p]:
                    match += 1
            b += loop_len
        rate = match / total if total else 0.0
        if rate > best_rate:
            best_phase, best_rate, best_ref = o, rate, ref

    # 각 블록이 레퍼런스와 충분히 일치하면 루프 인스턴스
    instances: list[LoopInstance] = []
    o = best_phase
    b = o
    while b + loop_len <= n:
        match = sum(1 for p in range(loop_len)
                    if per_bar_chord[b + p] == best_ref[p])
        if match / loop_len >= INSTANCE_THRESHOLD:
            instances.append(LoopInstance(b, b + loop_len))
            for p in range(loop_len):
                is_loop[b + p] = True
        b += loop_len
    if not instances:   # 폴백
        return 0, [LoopInstance(0, n)], [True] * n
    return best_phase, instances, is_loop


def analyze_structure(mir: MirResult, time_sig: str = "4/4") -> StructureResult:
    # 박자는 다운비트 트래커가 감지한 값 우선(없으면 time_sig)
    beats_per_bar = mir.beats_per_bar if getattr(mir, "beats_per_bar", 0) else (
        int(time_sig.split("/")[0]) if "/" in time_sig else 4)
    bar_times = _build_bar_grid(mir, beats_per_bar)
    n_bars = max(1, len(bar_times) - 1)

    per_bar_chord = []
    for b in range(n_bars):
        start = bar_times[b]
        end = bar_times[b + 1] if b + 1 < len(bar_times) else mir.duration
        per_bar_chord.append(_chord_for_bar(start, end, mir.chords))

    # 코드 지속 구간 병합
    segments: list[RawSegment] = []
    b = 0
    while b < n_bars:
        j = b
        while j + 1 < n_bars and per_bar_chord[j + 1] == per_bar_chord[b]:
            j += 1
        segments.append(RawSegment(
            start_bar=b, end_bar=j + 1,
            start_sec=bar_times[b],
            end_sec=bar_times[j + 1] if j + 1 < len(bar_times) else mir.duration,
            chord_name=per_bar_chord[b],
        ))
        b = j + 1

    loop_len = _detect_loop(per_bar_chord)
    loop_phase, loop_instances, is_loop_bar = _detect_loop_instances(per_bar_chord, loop_len)

    # 화성 리듬: 루프 안에서 코드 변경 횟수(평균)
    if loop_len > 0:
        changes_per_loop = []
        for start in range(0, n_bars, loop_len):
            window = per_bar_chord[start:start + loop_len]
            changes = sum(1 for k in range(1, len(window)) if window[k] != window[k - 1])
            changes_per_loop.append(changes + 1)  # +1 = 첫 코드
        harmonic_rhythm = sum(changes_per_loop) / len(changes_per_loop) if changes_per_loop else 0.0
    else:
        harmonic_rhythm = 0.0

    return StructureResult(
        beats_per_bar=beats_per_bar, bar_times=bar_times,
        per_bar_chord=per_bar_chord, segments=segments,
        loop_len=loop_len, harmonic_rhythm=harmonic_rhythm,
        loop_phase=loop_phase, loop_instances=loop_instances,
        is_loop_bar=is_loop_bar,
    )
