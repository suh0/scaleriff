"""프레이즈 생성 — 구조 생성기(리듬 셀 + AA' 모티프 + 컨투어 라인).

구조가 음악성을 만들고, 학습 모델(있으면)은 도수 사전분포로만 개입한다:
- 리듬 층: 박 단위 셀(정박 위주 어휘) → 마디 앞 절반(모티프)을 뒤 절반에
  그대로 반복(AA') — 외워서 다른 데 써먹기 좋은 리프 구조.
- 멜로디 층: 컨투어(아치/상행/하행/웨이브) 목표선 + 스텝모션 + 정박 코드톤
  앵커 + 비코드톤 3연속 금지 + 마지막 음 코드톤 해결.
- 모델 개입(있으면): blended(보간 백오프) 분포를 도수 가중에 곱하고,
  학습된 칸별 온셋 확률(_onset_probs)로 리듬 셀 가중치를 보정.
출력은 항상 **배정 스케일 안의 음만**(게이트), 그리드 토큰을
ml.representation.decode 로 example_phrase({midi, beat_pos, dur_beats})로 변환.
"""
from __future__ import annotations
import math
import random
import hashlib
import json

from ml.representation import (
    BOS, REST, HOLD, ONSET0, VOCAB, onset_token, is_onset, token_degree, decode,
    SCALE_DEGREES, QFAM_CHORD_TONES,
    STEPS_PER_BAR, quality_family, _nearest_midi,
)
from ml.model import is_trained
from analyze.theory import Chord, CHORD_SPECS


# ── 칸별 코드 계획 만들기 ────────────────────────────────────────
def build_step_plan(chord_events, n_steps):
    """chord_events: [(start_step, root_pc, quality)] (start_step 오름차순).
    반환: (roots[per-step], qfams[per-step])."""
    roots = [0] * n_steps
    qfams = ["maj"] * n_steps
    if not chord_events:
        return roots, qfams
    ev = sorted(chord_events)
    for idx, (s, root, qual) in enumerate(ev):
        end = ev[idx + 1][0] if idx + 1 < len(ev) else n_steps
        for i in range(max(0, s), min(n_steps, end)):
            roots[i] = root
            qfams[i] = quality_family(qual)
    # 첫 이벤트 앞 구간은 첫 코드로 채움
    first = ev[0][0]
    for i in range(0, min(n_steps, first)):
        roots[i] = ev[0][1]
        qfams[i] = quality_family(ev[0][2])
    return roots, qfams


def _choose_stepwise(pool, prev_deg, rng):
    # 가까운 음 강하게 선호(제곱) → 도약 억제, 매끈한 윤곽.
    # 단, 같은 음 연속은 soft하게 억제(거리 0이 최대가중되는 걸 상쇄, §같은음금지).
    weights = []
    for d in pool:
        w = 1.0 / (1 + abs(d - prev_deg)) ** 2
        if d == prev_deg:
            w *= 0.12
        weights.append(w)
    r = rng.random() * sum(weights)
    acc = 0.0
    for d, w in zip(pool, weights):
        acc += w
        if r <= acc:
            return d
    return pool[-1]


def _nearest_chord_tone(deg, cts):
    return min(cts, key=lambda c: abs(c - deg)) if cts else deg


# ── 리듬 층: 박 단위 셀(16분 4칸 안의 온셋 오프셋) — 정박 위주 ──
# 손 가중치 = 리프 구조의 하한(prior). 모델이 있으면 학습 온셋 통계를 곱한다.
_CELLS: list[tuple[tuple[int, ...], float]] = [
    ((0,), 3.0),            # ♩ 한 음
    ((0, 2), 5.0),          # ♪♪ — 기본 밀도
    ((0, 2, 3), 1.2),
    ((0, 1, 2), 0.8),
    ((0, 3), 1.2),          # 부점
    ((0, 1, 2, 3), 0.5),    # 16분 런 — 드물게
    ((2,), 0.5),            # 엇박 시작 — 드물게
    ((), 0.8),              # 쉼박(호흡)
]


def _onset_probs(model) -> "list[float] | None":
    """마디 내 16칸별 P(onset) — 일반 컨텍스트('*|*|metric')의 온셋 질량.

    학습 데이터의 리듬(어느 칸에서 음이 시작되는가) 통계를 리듬 셀 선택에
    반영하기 위한 것. 컨텍스트가 하나라도 비면 None(손 가중치만 사용)."""
    probs = []
    for metric in range(STEPS_PER_BAR):
        d = model.table.get(model._key("*", "*", metric, ()))
        if not d:
            return None
        tot = sum(d.values())
        probs.append(sum(c for t, c in d.items() if int(t) >= ONSET0) / tot)
    return probs


def _cell_likelihood(cell, p4) -> float:
    """셀의 학습 우도 = 칸별 온셋 확률의 곱(온셋 칸=p, 빈 칸=1-p)."""
    w = 1.0
    for off in range(4):
        p = min(0.95, max(0.05, p4[off]))      # 극단 확률 클램프
        w *= p if off in cell else (1.0 - p)
    return w


def _pick_cell(rng: random.Random, must_start=False, p4=None):
    pool = [(c, w * (_cell_likelihood(c, p4) if p4 else 1.0))
            for c, w in _CELLS
            if not must_start or (c and c[0] == 0)]
    r = rng.random() * sum(w for _, w in pool)
    acc = 0.0
    for c, w in pool:
        acc += w
        if r <= acc:
            return c
    return pool[-1][0]


def _bar_cells(rng: random.Random, beats: int, onset_probs=None):
    """마디 리듬 = 앞 절반 모티프를 뒤 절반에 그대로 반복(AA').

    onset_probs(있으면): 학습된 칸별 온셋 확률로 셀 가중치 보정."""
    half = max(1, beats // 2)
    motif = []
    for b in range(half):
        p4 = onset_probs[b * 4:(b + 1) * 4] if onset_probs else None
        motif.append(_pick_cell(rng, must_start=(b == 0), p4=p4))
    return (motif * ((beats + half - 1) // half))[:beats]


# ── 멜로디 층: 컨투어 목표선(스케일 인덱스 0~6 공간) ────────────
def _contour_target(shape: str, f: float) -> float:
    if shape == "asc":
        return 1.0 + 4.5 * f
    if shape == "desc":
        return 5.5 - 4.5 * f
    if shape == "wave":
        return 3.0 + 2.2 * math.sin(2 * math.pi * f)
    # arch: 정점을 55% 지점에
    if f <= 0.55:
        return 1.5 + 4.0 * (f / 0.55)
    return 5.5 - 3.5 * ((f - 0.55) / 0.45)


# 학습 테이블에 없는 스케일 라벨 → 근접 라벨 질의(백오프 L4 직행 방지).
# 실데이터(markov.json) 라벨: {메이저, 마이너, 도리안, 프리지안, 리디안,
# 믹솔리디안, 로크리안} — 아이오니안/에올리안만 별칭 폴백, 나머지는 안전망.
_SCALE_QUERY_FALLBACK = {
    "아이오니안": "메이저", "리디안": "메이저", "믹솔리디안": "메이저",
    "에올리안": "마이너", "프리지안": "마이너", "로크리안": "마이너",
    "메이저 펜타토닉": "메이저", "마이너 펜타토닉": "마이너", "블루스": "마이너",
}


def _query_scale(model, scale_kind: str) -> str:
    """모델 테이블에 있는 라벨이면 그대로, 없으면 근접 라벨로 질의."""
    if model.table.get(model._key("*", scale_kind, 0, ())):
        return scale_kind
    return _SCALE_QUERY_FALLBACK.get(scale_kind, scale_kind)


def melodic_grid(model, qfams, scale_kind, n_steps, rng, beats_per_bar=4):
    """구조 생성기 — 리듬 셀+AA' 모티프+컨투어 라인+정박 코드톤 앵커.

    모델(있으면)은 blended(보간 백오프) 분포를 도수 사전분포로만 곱한다.
    """
    deg_pool = sorted(SCALE_DEGREES.get(scale_kind, SCALE_DEGREES["메이저"]))
    npool = len(deg_pool)
    beats = beats_per_bar
    bar_steps = beats * 4
    n_bars = max(1, (n_steps + bar_steps - 1) // bar_steps)
    trained = is_trained(model)
    probs = _onset_probs(model) if trained else None
    cells = _bar_cells(rng, beats, probs)      # 리듬은 모든 마디 공유(반복 학습)
    onsets: list[int] = []
    empty_zones: set[int] = set()
    for bar in range(n_bars):
        for b, cell in enumerate(cells):
            st = bar * bar_steps + b * 4
            if not cell:
                empty_zones.update(range(st, min(n_steps, st + 4)))
            for off in cell:
                if st + off < n_steps:
                    onsets.append(st + off)
    onsets = sorted(set(onsets))
    if not onsets:
        return [REST] * n_steps

    # 지속/쉼 골격(온셋 사이 HOLD, 쉼박에서 끊김) — prev 컨텍스트·최종 조립 공용
    hold = [REST] * n_steps
    for j, s in enumerate(onsets):
        end = onsets[j + 1] if j + 1 < len(onsets) else n_steps
        for t in range(s + 1, end):
            if t in empty_zones:
                break
            hold[t] = HOLD

    shape = rng.choice(("arch", "asc", "desc", "wave"))
    q_scale = _query_scale(model, scale_kind) if trained else scale_kind
    prev_k = 0                                  # 근음 인덱스에서 출발
    run_nonchord = 0
    chosen: dict[int, int] = {}
    for i, s in enumerate(onsets):
        metric = s % STEPS_PER_BAR
        qfam = qfams[s] if s < len(qfams) else "maj"
        cts = {d for d in deg_pool if d in QFAM_CHORD_TONES.get(qfam, [])}
        prior = {}
        if trained:
            # 학습(fit)과 같은 의미의 prev = 직전 그리드 2스텝(HOLD/REST 포함, BOS 패딩)
            prev2 = tuple(BOS if p < 0
                          else onset_token(chosen[p]) if p in chosen
                          else hold[p]
                          for p in (s - 2, s - 1))
            bl = model.blended(qfam, q_scale, metric, prev2)
            mass = sum(bl.get(onset_token(d), 0.0) for d in deg_pool)
            if mass > 1e-9:                     # 스케일 내 온셋 도수만으로 재정규화
                prior = {d: bl.get(onset_token(d), 0.0) / mass for d in deg_pool}
        target = _contour_target(shape, i / max(1, len(onsets) - 1))
        force_chord = run_nonchord >= 2 and cts
        weights = []
        for k, d in enumerate(deg_pool):
            w = 0.03 + prior.get(d, 0.0)                   # 재정규화 prior + floor
            # floor 0.03: 모델 prior가 구조 가중치 대비 실질 발언권을 갖는 수준.
            dist = min(abs(k - prev_k), npool - abs(k - prev_k))
            w *= 1.0 / (1 + dist) ** 2                     # 스텝모션(도약 억제)
            if dist == 0:
                w *= 0.15                                  # 같은 음 연속 억제
            w *= 1.0 / (1 + abs(k - target))               # 컨투어 목표선
            if metric % 4 == 0 and d in cts:
                w *= 2.5                                   # 정박 코드톤 앵커
            if force_chord and d not in cts:
                w *= 0.05                                  # 비코드톤 3연속 금지
            weights.append(w)
        r = rng.random() * sum(weights)
        acc, deg = 0.0, deg_pool[-1]
        for d, w in zip(deg_pool, weights):
            acc += w
            if r <= acc:
                deg = d
                break
        prev_k = deg_pool.index(deg)
        chosen[s] = deg
        run_nonchord = 0 if deg in cts else run_nonchord + 1

    # 그리드 조립 — 골격(hold) 위에 온셋 토큰만 채움
    grid = hold
    for s in onsets:
        grid[s] = onset_token(chosen[s])
    # 마지막 음 코드톤으로 마무리(해결감)
    last = onsets[-1]
    qfam = qfams[last] if last < len(qfams) else "maj"
    cts = [d for d in deg_pool if d in QFAM_CHORD_TONES.get(qfam, [])]
    grid[last] = onset_token(_nearest_chord_tone(token_degree(grid[last]), cts))
    return grid


# ── 이론 프라이어 규칙 생성 — 부트스트랩 모델(make_default_model) 학습 데이터
#    합성 전용. 런타임 생성은 melodic_grid가 담당.
def rule_based_grid(qfams, scale_kind, n_steps, rng):
    """이론 프라이어 라인 — 밀도↓·호흡·스텝모션·코드톤 마무리로 음악성 보강."""
    deg_pool = sorted(SCALE_DEGREES.get(scale_kind, SCALE_DEGREES["메이저"]))
    prev_deg = 0
    sounding = False
    since_rest = 0          # 마지막 쉼 이후 연속 점유 칸 수(프레이즈 호흡용)
    run_nonchord = 0        # 연속 비코드톤(스케일음) 개수 — 3연속 금지(soft)
    grid = []
    last_onset = -1
    for i in range(n_steps):
        metric = i % STEPS_PER_BAR
        qfam = qfams[i] if i < len(qfams) else "maj"
        cts = [d for d in deg_pool if d in QFAM_CHORD_TONES.get(qfam, [])]
        strong = (metric % 4 == 0)
        half = (metric % 2 == 0)
        # 밀도 낮춤: 박마다 ~한 음, 16분은 드물게
        p_on = 0.55 if strong else 0.30 if half else 0.07
        if since_rest >= 6:           # 너무 길게 이어지면 쉼 유도(호흡)
            p_on *= 0.35
        if rng.random() < p_on:
            # 강박은 코드톤 강하게 선호. 스케일음 2연속이면 코드톤으로 유도(3연속 금지).
            force_chord = run_nonchord >= 2 and cts
            pool = cts if ((strong and cts and rng.random() < 0.8) or force_chord) else deg_pool
            deg = _choose_stepwise(pool or deg_pool, prev_deg, rng)
            grid.append(onset_token(deg))
            run_nonchord = 0 if (cts and deg in cts) else run_nonchord + 1
            prev_deg, sounding, last_onset = deg, True, i
            since_rest += 1
        elif sounding and rng.random() < 0.5:
            grid.append(HOLD)         # 음 길게(빽빽함 완화)
            since_rest += 1
        else:
            grid.append(REST)
            sounding = False
            since_rest = 0
    # 마지막 음은 코드톤으로 마무리(해결감)
    if last_onset >= 0:
        qfam = qfams[last_onset] if last_onset < len(qfams) else "maj"
        cts = [d for d in deg_pool if d in QFAM_CHORD_TONES.get(qfam, [])]
        grid[last_onset] = onset_token(_nearest_chord_tone(token_degree(grid[last_onset]), cts))
    return grid


# ── 공개 API ─────────────────────────────────────────────────────
def generate_phrase(model, chord_events, scale_kind, n_bars=2, seed=None, beats_per_bar=4):
    """chord_events: [(start_step, root_pc, quality)]. 반환 {notes, grid}."""
    rng = random.Random(seed)
    n_steps = n_bars * beats_per_bar * 4
    roots, qfams = build_step_plan(chord_events, n_steps)
    grid = melodic_grid(model, qfams, scale_kind, n_steps, rng, beats_per_bar)
    notes = decode(grid, roots)
    return {"notes": notes, "grid": grid}


# 스케일 종류 → 대표 코드 quality(코드톤 해결용). 7다이아토닉 모드 매핑.
_KIND_QUALITY = {
    "아이오니안": "maj7", "메이저": "maj7", "리디안": "maj7",
    "도리안": "m7", "프리지안": "m7", "에올리안": "m7", "마이너": "m7",
    "믹솔리디안": "dom7", "로크리안": "m7b5",
    "디미니시드": "dim7", "온음": "aug",
}


def _riff_score(grid, model, qfams, scale_kind) -> float:
    """후보 랭킹 점수 = 모델 평균 PMI(전 스텝) + 정박 코드톤 적중률.

    PMI = log p(토큰|컨텍스트) - log p(토큰): 토큰의 전역 빈도를 빼서
    "이 문맥에서 유난히 데이터스러운가"만 남긴다. 순수 로그우도는 REST/HOLD
    (스텝당 고확률)가 ONSET(12도수로 분산)보다 항상 유리해 음수 적은 후보만
    뽑는 밀도 편향이 있었음 — PMI는 밀도 중립.
    """
    deg_pool = set(SCALE_DEGREES.get(scale_kind, SCALE_DEGREES["메이저"]))
    hits = tot = 0
    for i, t in enumerate(grid):
        if is_onset(t) and i % 4 == 0:
            cts = QFAM_CHORD_TONES.get(qfams[i] if i < len(qfams) else "maj", [])
            tot += 1
            hits += int(token_degree(t) in cts and token_degree(t) in deg_pool)
    anchor = hits / tot if tot else 0.0
    if not is_trained(model):
        return anchor
    q_scale = _query_scale(model, scale_kind)
    base = model.table.get(model._key("*", "*", "*", ()), {})   # 전역 토큰 빈도
    btot = sum(base.values())
    ll, prev = 0.0, [BOS, BOS]
    for i, t in enumerate(grid):
        qfam = qfams[i] if i < len(qfams) else "maj"
        bl = model.blended(qfam, q_scale, i % STEPS_PER_BAR, tuple(prev[-2:]))
        mass = sum(bl.values())
        p = (bl.get(t, 0.0) + 1e-3) / (mass + 1e-3 * VOCAB) if mass else 1.0 / VOCAB
        p0 = (base.get(str(t), 0) + 1e-3) / (btot + 1e-3 * VOCAB) if btot else 1.0 / VOCAB
        ll += math.log(p) - math.log(p0)
        prev.append(t)
    return ll / len(grid) + anchor


def _kind_seed(kind: str) -> int:
    """스케일 종류명 → 결정적 시드(같은 종류는 항상 같은 리프)."""
    return sum((i + 1) * ord(c) for i, c in enumerate(kind))


def generate_scale_riff(model, scale_kind: str, n_bars=1, variant=0, beats_per_bar=4) -> list[dict]:
    """스케일 종류당 1개 리프(루트 0 상대값).

    음악적 파이프라인(generate_phrase)에 위임 — 학습 분포(있으면) 기반
    리듬·라인 + 쉼표 호흡 + 보이스리딩 + 코드톤 해결. 제약은 melodic_grid
    안에서 soft bias로 적용(첫박 코드톤·스케일음 3연속 금지·같은 음 반복
    억제). 종류명 시드로 결정적(같은 종류=같은 리프).
    """
    quality = _KIND_QUALITY.get(scale_kind, "maj7")
    events = [(0, 0, quality)]                       # 루트 0 기준 대표 코드
    base = _kind_seed(scale_kind) + variant * 1000   # variant = 재생성 변주(§8)
    # 후보 24개 생성 → 밀도 하한(<3음/마디) 기각 후 랭킹 점수 argmax 채택.
    # 결정적(같은 종류=같은 결과). 전부 밀도 미달이면 가장 음 많은 후보.
    min_notes = 3 * max(1, n_bars)
    _, qfams = build_step_plan(events, n_bars * beats_per_bar * 4)
    cands = [generate_phrase(model, events, scale_kind, n_bars=n_bars, seed=base + off,
                             beats_per_bar=beats_per_bar)
             for off in range(24)]
    ok = [c for c in cands if len(c["notes"]) >= min_notes]
    if not ok:
        return max(cands, key=lambda c: len(c["notes"]))["notes"]
    return max(ok, key=lambda c: _riff_score(c["grid"], model, qfams, scale_kind))["notes"]


def _make_riff(model, kind: str, max_bars: int, variant: int = 0, beats_per_bar=4) -> dict:
    """스케일 종류 1개의 리프 dict(상대값 + note_set/chord_tones/quality)."""
    quality = _KIND_QUALITY.get(kind, "maj7")
    qfam = quality_family(quality)
    return {
        "notes": generate_scale_riff(model, kind, n_bars=max_bars, variant=variant,
                                      beats_per_bar=beats_per_bar),
        "note_set": sorted(SCALE_DEGREES.get(kind, SCALE_DEGREES["메이저"])),
        "chord_tones": Chord("", 0, quality).chord_tones(),
        "quality": quality,
        "n_bars": max_bars,
        "variant": variant,
    }


def _tile_segment(timeline, seg) -> None:
    """구간의 종류 리프를 코드 근음으로 이조 + 구간 길이만큼 반복 타일링 → seg.example.

    같은 코드가 2마디면 1마디 리프가 두 번 반복된다(§3).
    """
    bpb = timeline.time_sig_beats()
    kind = seg.scale.kind if seg.scale else "메이저"
    data = timeline.scale_riffs[kind]
    rel = data["notes"]
    riff_beats = max(1, data["n_bars"]) * bpb
    shift = seg.chord.root if seg.chord.root <= 6 else seg.chord.root - 12
    seg_beats = timeline.beats_between(seg.start_sec, seg.end_sec)
    ex, t = [], 0.0
    while t < seg_beats - 1e-6:
        for n in rel:
            if n["beat_pos"] < riff_beats and t + n["beat_pos"] < seg_beats:
                ex.append({"midi": n["midi"] + shift,
                           "beat_pos": round(t + n["beat_pos"], 4),
                           "dur_beats": min(n["dur_beats"], seg_beats - t - n["beat_pos"])})
        t += riff_beats
    seg.example = ex


def bake_examples(timeline, model, max_bars=1):
    """빌드 1회: **스케일 종류당 1개** 리프(상대값) 생성 → 각 구간에 코드 근음으로
    이조·타일링 배정(§8). 결과는 timeline.scale_riffs와 seg.example에 저장.
    재생/스크럽 중에는 호출하지 않는다(아키텍처 불변식 §4).
    """
    riffs: dict = {}
    for seg in timeline.segments:
        kind = seg.scale.kind if seg.scale else "메이저"
        if kind not in riffs:
            riffs[kind] = _make_riff(model, kind, max_bars, beats_per_bar=timeline.time_sig_beats())
    timeline.scale_riffs = riffs
    for seg in timeline.segments:
        _tile_segment(timeline, seg)
    timeline.model_info = model.identity() if model is not None else {
        "source": "rule", "phrases": 0, "artifact": None, "sha256": None}
    return timeline


def _landing_pc(seg, goal):
    intervals = CHORD_SPECS.get(seg.chord.quality, ([], ""))[0]
    if goal == "third":
        degrees = [d for d in intervals if d in (3, 4)]
    elif goal == "seventh":
        degree = {"maj7": 11, "m7": 10, "dom7": 10, "7": 10,
                  "m7b5": 10, "dim7": 9}.get(seg.chord.quality)
        degrees = [] if degree is None else [degree]
    elif goal == "root":
        degrees = [0] if intervals else []
    else:
        degrees = intervals
    return next(((seg.chord.root + d) % 12 for d in degrees
                 if (seg.chord.root + d) % 12 in seg.note_set), None)


def _off(beat) -> bool:
    return abs(beat - round(beat)) > 1e-7


def _onsets_ok(beats, end) -> bool:
    """리프 온셋 규칙 — 인접 간격 4박 미만(마지막 음~구간 끝 포함), 엇박 연속 금지."""
    return (all(b - a < 4 for a, b in zip(beats, beats[1:] + [end]))
            and not any(_off(a) and _off(b) for a, b in zip(beats, beats[1:])))


def _step(a, b, note_set) -> bool:
    """스케일 한 칸 이동 — 1~3반음이고 사이에 그 스케일 음이 없음(펜타토닉 단3도 포함)."""
    lo, hi = sorted((a, b))
    return 0 < hi - lo <= 3 and not any(x % 12 in note_set for x in range(lo + 1, hi))


def _fill_onsets(beats, end) -> list:
    """규칙 위반 보정 — 4박 공백 가운데·엇박 연속 사이에 정박 추가(정박은 두 규칙을 깨지 않음)."""
    beats = sorted(beats)
    i = 0
    while i < len(beats):
        a, b = beats[i], beats[i + 1] if i + 1 < len(beats) else end
        if b - a >= 4:
            beats.insert(i + 1, float(round((a + b) / 2)))
        elif i + 1 < len(beats) and _off(a) and _off(b) and a < math.floor(b):
            beats.insert(i + 1, float(math.floor(b)))
        else:
            i += 1
    return beats


def bake_progression(timeline, model, start_sec, end_sec, goal="third", variant=0, density=1.0,
                     count=None):
    """Bake the selected source interval using its actual chords and assigned note sets.

    Returns {notes, start_sec, end_sec, goal, variant, density, landings, model_info}.
    notes are {midi, start_sec, duration_sec, velocity} in absolute source seconds.
    landings describe each internal chord entry and the final note, with target_pc=None
    and supported=False when that chord/assigned scale cannot support the requested goal.
    seg.example remains in segment-relative beats; examples outside the selection survive.
    goal=None: no landing constraint (free practice, scale notes only).
    count=(lo, hi): the whole selection (= one riff) gets lo..hi notes (chord entries included,
    so never fewer than the chord count) instead of density.
    Riff rules: 8th-note grid, gaps < 4 beats, no two offbeats in a row, adjacent leaps < 12
    semitones, no pitch three times in a row; then (soft, skipped when nothing fits) non-chord
    tones entered and left by step, a leap of a 4th or more followed by a step back, a
    single highest note, no repeated pitch, and no target pitch class right before a landing.
    Chord tones are weighted up (downbeat x4, offbeat x1.8). If 20 draws miss the onset rules, downbeats are
    added (the count may then exceed hi).
    Call during preparation or an explicit user action, never from a playback tick.
    """
    if goal not in (None, "third", "seventh", "root", "chord_tone"):
        raise ValueError("goal must be None, third, seventh, root or chord_tone")
    if count is not None and not 1 <= count[0] <= count[1]:
        raise ValueError("count must be (lo, hi) with 1 <= lo <= hi")
    if not all(math.isfinite(x) for x in (start_sec, end_sec, density)) or density <= 0:
        raise ValueError("finite source times and positive density are required")
    if end_sec <= start_sec:
        raise ValueError("end_sec must follow start_sec")
    parts = [(s, max(start_sec, s.start_sec), min(end_sec, s.end_sec))
             for s in timeline.segments if s.start_sec < end_sec and s.end_sec > start_sec]
    info = model.identity() if model is not None else {
        "source": "rule", "phrases": 0, "artifact": None, "sha256": None}
    result = {"notes": [], "start_sec": start_sec, "end_sec": end_sec, "goal": goal,
              "variant": variant, "density": density, "landings": [], "model_info": info}
    if not parts:
        return result
    if any(not seg.note_set for seg, _, _ in parts):
        raise ValueError("each selected chord needs an assigned note_set")
    b0, b1 = timeline.beat_at(start_sec), timeline.beat_at(end_sec)
    plan = [(seg.chord.name, seg.chord.root, seg.chord.quality, a, b, sorted(seg.note_set))
            for seg, a, b in parts]
    seed = int.from_bytes(hashlib.sha256(json.dumps(
        [plan, goal, variant] + ([list(count)] if count else []), ensure_ascii=False).encode("utf-8")).digest()[:8], "big")
    rng = random.Random(seed)
    bpb = timeline.time_sig_beats()
    trained = is_trained(model)
    probs = _onset_probs(model) if trained else None
    cells = _bar_cells(rng, bpb, probs)
    mandatory = {a for _, a, _ in parts}
    boundaries = sorted({start_sec, end_sec} | {t for _, a, b in parts for t in (a, b)})
    candidates = set(mandatory)
    preferred = []
    for step in range(int(math.ceil((b1 - b0) * 2))):      # 8분음표 격자
        beat = b0 + step / 2
        sec = timeline.time_at_beat(beat)
        # Beat interpolation can differ from a manual chord boundary by one float ULP.
        sec = next((t for t in boundaries if abs(sec - t) < 1e-9), sec)
        if any(a <= sec < b for _, a, b in parts):
            candidates.add(sec)
            if step % 2 * 2 in cells[(step // 2) % bpb]:
                preferred.append(sec)
    extra = sorted(candidates - mandatory - set(preferred))
    preferred = sorted(set(preferred) - mandatory)
    total = min(len(candidates), max(len(mandatory), rng.randint(*count) if count
                                     else int(round((b1 - b0) * 1.5 * density))))
    for _ in range(20):
        rng.shuffle(preferred)
        rng.shuffle(extra)
        onsets = sorted(mandatory | set((preferred + extra)[:total - len(mandatory)]))
        if _onsets_ok([timeline.beat_at(t) for t in onsets], b1):
            break
    else:
        known = {timeline.beat_at(t): t for t in onsets}
        onsets = [known.get(b, timeline.time_at_beat(b)) for b in _fill_onsets(list(known), b1)]
        onsets = [t for t in onsets if any(a <= t < b for _, a, b in parts)]
    shape = rng.choice(("arch", "asc", "desc", "wave"))
    prev_midi, prev2, prev_tokens, previous_end = 71, None, [BOS, BOS], b0
    prev_nct, peak = False, None
    forced = [_landing_pc(next(p for p in parts if p[1] <= t < p[2])[0], goal)
              if goal in ("third", "seventh", "root") and (
                  k == len(onsets) - 1 or (t in mandatory and t > start_sec)) else None
              for k, t in enumerate(onsets)] + [None, None]
    for i, sec in enumerate(onsets):
        seg, _, boundary = next(p for p in parts if p[1] <= sec < p[2])
        beat = timeline.beat_at(sec)
        target = _landing_pc(seg, goal)
        landing_kind = None if goal is None else "final" if i == len(onsets) - 1 else (
            "change" if sec in mandatory and sec > start_sec else None)
        pool = [m for m in range(60, 84) if m % 12 in seg.note_set]
        chord_pool = [m for m in pool if m % 12 in seg.chord_tones()]
        if landing_kind:
            pool = (chord_pool or pool) if goal == "chord_tone" or target is None else [
                m for m in pool if m % 12 == target]
        if i:   # 우선순위 규칙 — pool을 비우지 않을 때만 적용(못 지키면 그 규칙만 건너뜀)
            f1, f2 = forced[i + 1], forced[i + 2]
            cts, ns = seg.chord_tones(), seg.note_set
            leap = prev_midi - prev2 if prev2 is not None and abs(prev_midi - prev2) >= 5 else 0
            for keep in (
                lambda m: abs(m - prev_midi) < 12,                          # 인접 도약 1옥타브 미만
                lambda m: not m == prev_midi == prev2 and m % 12 != f1,     # 같은 음 3연속, 착지 직전엔 목표음 피함
                lambda m: _step(prev_midi, m, ns) or (                      # 비화성음은 순차 진입·해결
                    not prev_nct and m % 12 in cts),
                lambda m: not leap or (_step(prev_midi, m, ns)              # 4도 이상 도약 뒤 반대 순차
                                       and (m - prev_midi) * leap < 0),
                lambda m: m != peak,                                        # 최고음은 한 번만
                lambda m: m != prev_midi,                                   # 같은 음 반복 금지
            ):
                pool = [m for m in pool if keep(m)] or pool
        gap = max(0, int(round((beat - previous_end) * 4)))
        prev_tokens.extend([REST] * min(2, gap))
        prior = {}
        if trained:
            kind = seg.scale.kind if seg.scale else "메이저"
            prior = model.blended(quality_family(seg.chord.quality), _query_scale(model, kind),
                                  int(round(beat * 4)) % (bpb * 4), tuple(prev_tokens[-2:]))
        mass = sum(prior.get(onset_token((m - seg.chord.root) % 12), 0) for m in pool)
        contour = 62 + 2 * _contour_target(shape, i / max(1, len(onsets) - 1))
        weights = []
        for midi in pool:
            p = prior.get(onset_token((midi - seg.chord.root) % 12), 0) / mass if mass else 0
            weight = (.03 + p) / (1 + abs(midi - prev_midi)) ** 1.5
            weight /= 1 + abs(midi - contour) * .15
            if midi == prev_midi:
                weight *= .2
            if midi % 12 in seg.chord_tones():                         # 코드톤 선호(정박 > 엇박)
                weight *= 4 if abs(beat - round(beat)) < 1e-7 else 1.8
            weights.append(weight)
        midi = rng.choices(pool, weights=weights)[0]
        next_sec = onsets[i + 1] if i + 1 < len(onsets) else end_sec
        end_beat = min(timeline.beat_at(min(next_sec, boundary, end_sec)), beat + 1)
        note_end = min(boundary, end_sec, timeline.time_at_beat(beat + .9 * (end_beat - beat)))
        note = {"midi": midi, "start_sec": sec, "duration_sec": note_end - sec,
                "velocity": 86 if abs(beat - round(beat)) < 1e-7 else 74}
        result["notes"].append(note)
        if landing_kind:
            result["landings"].append({"at_sec": sec, "chord": seg.chord.name,
                                       "kind": landing_kind, "target_pc": target,
                                       "supported": target is not None, "actual_pc": midi % 12})
        prev2, prev_midi = prev_midi, midi
        prev_nct = midi % 12 not in seg.chord_tones()
        peak = midi if peak is None else max(peak, midi)
        prev_tokens.append(onset_token((midi - seg.chord.root) % 12))
        prev_tokens.extend([HOLD] * min(2, max(0, int(timeline.beats_between(sec, note_end) * 4) - 1)))
        previous_end = timeline.beat_at(note_end)
    write_examples(timeline, start_sec, end_sec, result["notes"])
    timeline.model_info = info
    return result


def write_examples(timeline, start_sec, end_sec, notes):
    """[start, end) 구간의 seg.example을 notes(절대초)로 교체 — 구간 밖 예시는 보존."""
    parts = [(s, max(start_sec, s.start_sec), min(end_sec, s.end_sec))
             for s in timeline.segments if s.start_sec < end_sec and s.end_sec > start_sec]
    for seg, a, b in parts:
        segment_beat = timeline.beat_at(seg.start_sec)
        kept = []
        for n in seg.example:
            ns = timeline.time_at_beat(segment_beat + n["beat_pos"])
            ne = timeline.time_at_beat(segment_beat + n["beat_pos"] + n["dur_beats"])
            if ne <= a or ns >= b:
                kept.append(n)
            else:
                for left, right in ((ns, min(ne, a)), (max(ns, b), ne)):
                    if right > left:
                        kept.append({**n, "beat_pos": timeline.beat_at(left) - segment_beat,
                                     "dur_beats": timeline.beats_between(left, right)})
        for n in notes:
            if a <= n["start_sec"] < b:
                kept.append({"midi": n["midi"], "beat_pos": timeline.beat_at(n["start_sec"]) - segment_beat,
                             "dur_beats": timeline.beats_between(n["start_sec"], n["start_sec"] + n["duration_sec"]),
                             "velocity": n["velocity"]})
        seg.example = sorted(kept, key=lambda n: n["beat_pos"])


def chord_patterns(timeline, bars_per_riff=2):
    """리프 패턴 = 곡 스케일 2마디 리프 1종(모든 창) + 디투어 마디용 1마디 리프(로컬 스케일별, overlay).

    창을 순서대로 잘라 묶으면 디투어 위치마다 패턴이 갈려 리프 수가 불어난다 — 디투어만 마디 단위로 덧씌운다.
    다른 코드 구간에는 transpose_riff로 도수 이동. 패턴 수 = 최소 리프 수.
    """
    bars = list(timeline.bar_times)
    if len(bars) < 2:
        bar = timeline.beat_sec() * timeline.time_sig_beats()
        bars = [i * bar for i in range(int(math.ceil(timeline.total_sec() / bar)) + 1)]

    def segs_in(a, b):
        return [s for s in timeline.segments if s.start_sec < b and s.end_sec > a]

    windows = [(bars[i], bars[min(i + bars_per_riff, len(bars) - 1)])
               for i in range(0, len(bars) - 1, bars_per_riff)]
    windows = [w for w in windows if segs_in(*w)]
    if not windows:
        return []
    # 리프는 디투어 없는 첫 온전한(짧은 마지막 창 제외) 창에서 굽는다(spans[0])
    full = timeline.beats_between(*windows[0])
    clean = [w for w in windows if timeline.beats_between(*w) >= full - 1e-6
             and not any(s.is_detour for s in segs_in(*w))]
    first = clean[0] if clean else windows[0]
    home = next((s.scale.name for s in timeline.segments if not s.is_detour and s.scale), "곡 스케일")
    patterns = [{"label": f"{home} · {bars_per_riff}마디",
                 "spans": [first] + [w for w in windows if w != first], "overlay": False}]
    groups = {}
    for a, b in zip(bars, bars[1:]):
        segs = segs_in(a, b)
        if not any(s.is_detour for s in segs):
            continue
        b0 = timeline.beat_at(a)
        runs = []   # (상대 박, note_set, 이름) — 같은 스케일이 이어지면 하나로
        for s in segs:
            ns = tuple(sorted(s.note_set))
            if not runs or runs[-1][1] != ns:
                runs.append((round(timeline.beat_at(max(a, s.start_sec)) - b0, 3), ns,
                             s.scale.name if s.scale else s.chord.name))
        key = (round(timeline.beats_between(a, b), 3),) + tuple(r[:2] for r in runs)
        groups.setdefault(key, {"label": "→".join(r[2] for r in runs) + " · 1마디",
                                "spans": [], "overlay": True})["spans"].append((a, b))
    return patterns + sorted(groups.values(), key=lambda p: -len(p["spans"]))


def _degree(note_set, pc):
    """정렬된 note_set에서 pc의 스케일 번호 — 없으면 바로 아래 도수."""
    return max((i for i, x in enumerate(note_set) if x <= pc), default=len(note_set) - 1)


def transpose_riff(timeline, notes, src_a, dst_a, goal=None, landing_secs=()):
    """src_a에서 만든 리프를 dst_a 창으로 — 상대 박 유지, 음은 각 박의 코드 근음 차만큼 스케일 도수 이동.

    같은 스케일이면 근음→근음·3도→3도로 옮겨지고 스케일 밖으로 나가지 않는다.
    착지음(landing_secs)은 dst 코드의 목표음 중 가장 가까운 음으로 맞춘다(펜타 등 대비).
    """
    off = timeline.beat_at(dst_a) - timeline.beat_at(src_a)
    out = []
    for n in notes:
        start = timeline.beat_at(n["start_sec"])
        s_new = timeline.time_at_beat(start + off)
        e_new = timeline.time_at_beat(timeline.beat_at(n["start_sec"] + n["duration_sec"]) + off)
        src, dst = timeline.segment_at(n["start_sec"]), timeline.segment_at(s_new)
        midi = n["midi"]
        if src and dst and src.note_set and dst.note_set:
            sset, dset = sorted(src.note_set), sorted(dst.note_set)
            octave, pc = divmod(midi, 12)
            # 스케일 번호(옥타브 포함) — 스케일이 다르면 dst 스케일에서 바로 아래 도수로 읽는다
            idx = _degree(dset, pc) + len(dset) * octave
            steps = _degree(dset, dst.chord.root) - _degree(sset, src.chord.root)
            o, i = divmod(idx + steps, len(dset))
            midi = 12 * o + dset[i]
            if any(abs(n["start_sec"] - t) < 1e-9 for t in landing_secs) and goal:
                targets = ({pc for pc in dst.chord_tones() if pc in dst.note_set}
                           if goal == "chord_tone" else {_landing_pc(dst, goal)} - {None})
                if targets:
                    midi = min((m for m in range(midi - 6, midi + 7) if m % 12 in targets),
                               key=lambda m: abs(m - midi))
            # 범위 밖이거나 직전 음과 1옥타브 이상 벌어지면 직전 음에 가까운 옥타브로
            prev = out[-1]["midi"] if out else midi
            if not 60 <= midi <= 83 or abs(midi - prev) >= 12:
                midi = _nearest_midi(midi % 12, prev, 60, 83)
        out.append({**n, "midi": midi, "start_sec": s_new, "duration_sec": e_new - s_new})
    return out


def allocate(patterns, n):
    """리프 n개를 패턴별 변형 수로 배분 — 패턴당 1개 후 '등장/변형'이 큰 패턴부터 하나씩."""
    counts = [1] * len(patterns)
    for _ in range(n - len(patterns)):
        open_ = [i for i, p in enumerate(patterns) if counts[i] < len(p["spans"])]
        if not open_:
            break
        counts[max(open_, key=lambda i: len(patterns[i]["spans"]) / counts[i])] += 1
    return counts


if __name__ == "__main__":
    ev = [(0, 2, "m7"), (16, 7, "7")]   # Dm7 → G7 (2마디)
    out = generate_phrase(None, ev, "도리안", n_bars=2, seed=1)
    print("notes:", out["notes"])
