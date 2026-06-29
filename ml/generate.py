"""프레이즈 생성 — 학습 모델(있으면) 또는 이론 프라이어 규칙(폴백).

출력은 항상 **배정 스케일 안의 음만**(게이트)으로 제한하고, 그리드 토큰을
ml.representation.decode 로 example_phrase({midi, beat_pos, dur_beats})로 변환.
리듬은 그리드(onset/HOLD/REST)로, 멜로디는 도수로 함께 생성된다.
"""
from __future__ import annotations
import random

from ml.representation import (
    REST, HOLD, BOS, onset_token, is_onset, token_degree, decode,
    SCALE_DEGREES, QFAM_CHORD_TONES,
    STEPS_PER_BAR, quality_family,
)
from ml.model import MarkovModel, is_trained


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


# ── 가중 추출 ────────────────────────────────────────────────────
def _weighted(dist: dict[int, int], rng: random.Random) -> int:
    items = list(dist.items())
    total = sum(c for _, c in items)
    r = rng.random() * total
    acc = 0.0
    for tok, c in items:
        acc += c
        if r <= acc:
            return tok
    return items[-1][0]


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


# ── 이론 프라이어 규칙 생성(데이터/모델 없을 때 폴백) ───────────
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


# ── 모델 기반 생성(게이트 적용) ─────────────────────────────────
def model_grid(model: MarkovModel, qfams, scale_kind, n_steps, rng, onset_damp=0.4):
    """2단계 샘플링: 먼저 쉼/지속/음 카테고리 결정(밀도 댐핑) → 음이면 도수 선택.

    onset 토큰이 12종이라 합산 질량이 부풀어 과밀해지는 문제를 방지(빽빽함 완화).
    """
    deg_pool = sorted(SCALE_DEGREES.get(scale_kind, SCALE_DEGREES["메이저"]))
    allowed = set(deg_pool)
    order = model.order
    prev = [BOS] * order
    sounding = False
    since_rest = 0
    run_nonchord = 0        # 연속 비코드톤 개수 — 3연속 금지(soft)
    prev_deg = None
    last_onset = -1
    grid = []
    for i in range(n_steps):
        metric = i % STEPS_PER_BAR
        qfam = qfams[i] if i < len(qfams) else "maj"
        cts = {d for d in deg_pool if d in QFAM_CHORD_TONES.get(qfam, [])}
        dist = model.counts(qfam, scale_kind, metric, tuple(prev[-order:]))
        rest_w = dist.get(REST, 0) + 1e-6
        hold_w = float(dist.get(HOLD, 0)) if sounding else 0.0
        onset_items = {t: c for t, c in dist.items()
                       if is_onset(t) and token_degree(t) in allowed}
        # ── soft 제약: 분포 재가중(파괴적 오버라이드 아님) ──
        force_chord = run_nonchord >= 2 and cts
        biased = {}
        for t, c in onset_items.items():
            d = token_degree(t)
            w = float(c)
            if d == prev_deg:                       # 같은 음 연속 억제
                w *= 0.12
            if metric == 0 and d in cts:            # 다운비트 코드톤 선호
                w *= 2.0
            if force_chord and d not in cts:        # 스케일음 3연속 금지
                w *= 0.05
            biased[t] = w
        onset_items = biased
        onset_w = sum(onset_items.values()) * onset_damp
        if since_rest >= 6:                # 호흡: 길게 이어지면 쉼 유도
            onset_w *= 0.4
            rest_w *= 1.6
        total = rest_w + hold_w + onset_w
        if total <= 0:
            tok = REST
        else:
            r = rng.random() * total
            if r < rest_w:
                tok = REST
            elif r < rest_w + hold_w:
                tok = HOLD
            else:
                tok = _weighted(onset_items, rng) if onset_items else REST
        grid.append(tok)
        if is_onset(tok):
            sounding, last_onset = True, i
            since_rest += 1
            deg = token_degree(tok)
            run_nonchord = 0 if deg in cts else run_nonchord + 1
            prev_deg = deg
        elif tok == HOLD:
            since_rest += 1
        else:
            sounding = False
            since_rest = 0
        prev.append(tok)
    if last_onset >= 0:                    # 마지막 음 코드톤으로 마무리
        qfam = qfams[last_onset] if last_onset < len(qfams) else "maj"
        cts = [d for d in deg_pool if d in QFAM_CHORD_TONES.get(qfam, [])]
        grid[last_onset] = onset_token(
            _nearest_chord_tone(token_degree(grid[last_onset]), cts))
    return grid


# ── 공개 API ─────────────────────────────────────────────────────
def generate_phrase(model, chord_events, scale_kind, n_bars=2, seed=None):
    """chord_events: [(start_step, root_pc, quality)]. 반환 {notes, grid}."""
    rng = random.Random(seed)
    n_steps = n_bars * STEPS_PER_BAR
    roots, qfams = build_step_plan(chord_events, n_steps)
    if is_trained(model):
        grid = model_grid(model, qfams, scale_kind, n_steps, rng)
    else:
        grid = rule_based_grid(qfams, scale_kind, n_steps, rng)
    notes = decode(grid, roots)
    return {"notes": notes, "grid": grid}


# 스케일 종류 → 대표 코드 quality(코드톤 해결용). 7다이아토닉 모드 매핑.
_KIND_QUALITY = {
    "아이오니안": "maj7", "메이저": "maj7", "리디안": "maj7",
    "도리안": "m7", "프리지안": "m7", "에올리안": "m7", "마이너": "m7",
    "믹솔리디안": "dom7", "로크리안": "m7b5",
}


def _kind_seed(kind: str) -> int:
    """스케일 종류명 → 결정적 시드(같은 종류는 항상 같은 리프)."""
    return sum((i + 1) * ord(c) for i, c in enumerate(kind))


def generate_scale_riff(model, scale_kind: str, n_bars=1) -> list[dict]:
    """스케일 종류당 1개 리프(루트 0 상대값).

    초기 음악적 파이프라인(generate_phrase)에 위임 — 학습 분포(있으면) 기반
    리듬·라인 + 쉼표 호흡 + 보이스리딩 + 코드톤 해결. 제약은 model_grid/
    rule_based_grid 안에서 soft bias로 적용(첫박 코드톤·스케일음 3연속 금지·
    같은 음 반복 억제). 종류명 시드로 결정적(같은 종류=같은 리프).
    """
    quality = _KIND_QUALITY.get(scale_kind, "maj7")
    events = [(0, 0, quality)]                       # 루트 0 기준 대표 코드
    base = _kind_seed(scale_kind)
    # 밀도 하한 거부샘플링: 분포는 그대로 두되 너무 빈(<3음/마디) 추출만 기각.
    # 결정적(같은 종류=같은 결과). 끝까지 못 채우면 가장 음 많은 후보 채택.
    min_notes = 3 * max(1, n_bars)
    best: list[dict] = []
    for off in range(24):
        notes = generate_phrase(model, events, scale_kind,
                                n_bars=n_bars, seed=base + off)["notes"]
        if len(notes) >= min_notes:
            return notes
        if len(notes) > len(best):
            best = notes
    return best


def _make_riff(model, kind: str, max_bars: int) -> dict:
    """스케일 종류 1개의 리프 dict(상대값 + note_set/chord_tones/quality)."""
    from ml.representation import SCALE_DEGREES, QFAM_CHORD_TONES, quality_family
    quality = _KIND_QUALITY.get(kind, "maj7")
    qfam = quality_family(quality)
    return {
        "notes": generate_scale_riff(model, kind, n_bars=max_bars),
        "note_set": sorted(SCALE_DEGREES.get(kind, SCALE_DEGREES["메이저"])),
        "chord_tones": sorted(QFAM_CHORD_TONES.get(qfam, QFAM_CHORD_TONES["maj"])),
        "quality": quality,
        "n_bars": max_bars,
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
