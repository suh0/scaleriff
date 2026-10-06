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

from ml.representation import (
    BOS, REST, HOLD, ONSET0, VOCAB, onset_token, is_onset, token_degree, decode,
    SCALE_DEGREES, QFAM_CHORD_TONES,
    STEPS_PER_BAR, quality_family,
)
from ml.model import is_trained


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
    return (motif + motif)[:beats]


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
}


def _query_scale(model, scale_kind: str) -> str:
    """모델 테이블에 있는 라벨이면 그대로, 없으면 근접 라벨로 질의."""
    if model.table.get(model._key("*", scale_kind, 0, ())):
        return scale_kind
    return _SCALE_QUERY_FALLBACK.get(scale_kind, scale_kind)


def melodic_grid(model, qfams, scale_kind, n_steps, rng):
    """구조 생성기 — 리듬 셀+AA' 모티프+컨투어 라인+정박 코드톤 앵커.

    모델(있으면)은 blended(보간 백오프) 분포를 도수 사전분포로만 곱한다.
    """
    deg_pool = sorted(SCALE_DEGREES.get(scale_kind, SCALE_DEGREES["메이저"]))
    npool = len(deg_pool)
    beats = STEPS_PER_BAR // 4                 # 16분 4칸 = 1박
    n_bars = max(1, n_steps // STEPS_PER_BAR)
    trained = is_trained(model)
    probs = _onset_probs(model) if trained else None
    cells = _bar_cells(rng, beats, probs)      # 리듬은 모든 마디 공유(반복 학습)
    onsets: list[int] = []
    empty_zones: set[int] = set()
    for bar in range(n_bars):
        for b, cell in enumerate(cells):
            st = bar * STEPS_PER_BAR + b * 4
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
def generate_phrase(model, chord_events, scale_kind, n_bars=2, seed=None):
    """chord_events: [(start_step, root_pc, quality)]. 반환 {notes, grid}."""
    rng = random.Random(seed)
    n_steps = n_bars * STEPS_PER_BAR
    roots, qfams = build_step_plan(chord_events, n_steps)
    grid = melodic_grid(model, qfams, scale_kind, n_steps, rng)
    notes = decode(grid, roots)
    return {"notes": notes, "grid": grid}


# 스케일 종류 → 대표 코드 quality(코드톤 해결용). 7다이아토닉 모드 매핑.
_KIND_QUALITY = {
    "아이오니안": "maj7", "메이저": "maj7", "리디안": "maj7",
    "도리안": "m7", "프리지안": "m7", "에올리안": "m7", "마이너": "m7",
    "믹솔리디안": "dom7", "로크리안": "m7b5",
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


def generate_scale_riff(model, scale_kind: str, n_bars=1, variant=0) -> list[dict]:
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
    _, qfams = build_step_plan(events, n_bars * STEPS_PER_BAR)
    cands = [generate_phrase(model, events, scale_kind, n_bars=n_bars, seed=base + off)
             for off in range(24)]
    ok = [c for c in cands if len(c["notes"]) >= min_notes]
    if not ok:
        return max(cands, key=lambda c: len(c["notes"]))["notes"]
    return max(ok, key=lambda c: _riff_score(c["grid"], model, qfams, scale_kind))["notes"]


def _make_riff(model, kind: str, max_bars: int, variant: int = 0) -> dict:
    """스케일 종류 1개의 리프 dict(상대값 + note_set/chord_tones/quality)."""
    quality = _KIND_QUALITY.get(kind, "maj7")
    qfam = quality_family(quality)
    return {
        "notes": generate_scale_riff(model, kind, n_bars=max_bars, variant=variant),
        "note_set": sorted(SCALE_DEGREES.get(kind, SCALE_DEGREES["메이저"])),
        "chord_tones": sorted(QFAM_CHORD_TONES.get(qfam, QFAM_CHORD_TONES["maj"])),
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
    seg_beats = max(1, seg.end_bar - seg.start_bar) * bpb
    ex, t = [], 0.0
    while t < seg_beats - 1e-6:
        for n in rel:
            if n["beat_pos"] < riff_beats and t + n["beat_pos"] < seg_beats:
                ex.append({"midi": n["midi"] + shift,
                           "beat_pos": round(t + n["beat_pos"], 4),
                           "dur_beats": n["dur_beats"]})
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
            riffs[kind] = _make_riff(model, kind, max_bars)
    timeline.scale_riffs = riffs
    for seg in timeline.segments:
        _tile_segment(timeline, seg)
    return timeline


def rebake_kind(timeline, model, kind: str, max_bars=1) -> dict:
    """리프 재생성 — 같은 종류의 다른 변주(시드 변경) + 그 종류 구간 전부 재타일링."""
    v = (timeline.scale_riffs.get(kind) or {}).get("variant", 0) + 1
    timeline.scale_riffs[kind] = _make_riff(model, kind, max_bars, variant=v)
    for seg in timeline.segments:
        if seg.scale and seg.scale.kind == kind:
            _tile_segment(timeline, seg)
    return timeline.scale_riffs[kind]


def bake_segment(timeline, seg, model, max_bars=1):
    """단일 구간 재굽기 — 악보 화면 수동 코드 수정 후 그 구간 리프만 갱신.

    새 스케일 종류면 timeline.scale_riffs에 추가하고, seg.example을 다시 타일링.
    """
    kind = seg.scale.kind if seg.scale else "메이저"
    if kind not in timeline.scale_riffs:
        timeline.scale_riffs[kind] = _make_riff(model, kind, max_bars)
    _tile_segment(timeline, seg)
    return timeline


if __name__ == "__main__":
    ev = [(0, 2, "m7"), (16, 7, "7")]   # Dm7 → G7 (2마디)
    out = generate_phrase(None, ev, "도리안", n_bars=2, seed=1)
    print("notes:", out["notes"])
