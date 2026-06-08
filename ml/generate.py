"""프레이즈 생성 — 학습 모델(있으면) 또는 이론 프라이어 규칙(폴백).

출력은 항상 **배정 스케일 안의 음만**(게이트)으로 제한하고, 그리드 토큰을
ml.representation.decode 로 example_phrase({midi, beat_pos, dur_beats})로 변환.
리듬은 그리드(onset/HOLD/REST)로, 멜로디는 도수로 함께 생성된다.
"""
from __future__ import annotations
import random

from ml.representation import (
    REST, HOLD, BOS, onset_token, is_onset, token_degree, decode,
    SCALE_DEGREES, QFAM_CHORD_TONES, allowed_onset_degrees,
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
    # 가까운 음 강하게 선호(제곱) → 도약 억제, 매끈한 윤곽
    weights = [1.0 / (1 + abs(d - prev_deg)) ** 2 for d in pool]
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
            # 강박은 코드톤 강하게 선호, 약박은 스텝모션
            pool = cts if (strong and cts and rng.random() < 0.8) else deg_pool
            deg = _choose_stepwise(pool or deg_pool, prev_deg, rng)
            grid.append(onset_token(deg))
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
    last_onset = -1
    grid = []
    for i in range(n_steps):
        metric = i % STEPS_PER_BAR
        qfam = qfams[i] if i < len(qfams) else "maj"
        dist = model.counts(qfam, scale_kind, metric, tuple(prev[-order:]))
        rest_w = dist.get(REST, 0) + 1e-6
        hold_w = float(dist.get(HOLD, 0)) if sounding else 0.0
        onset_items = {t: c for t, c in dist.items()
                       if is_onset(t) and token_degree(t) in allowed}
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


def bake_examples(timeline, model, max_bars=2):
    """빌드/연습 진입 시 1회: 각 구간의 활성 스케일로 example_phrase 생성(§4).

    재생/스크럽 중에는 호출하지 않는다(아키텍처 불변식). 결과는 seg.example에 저장.
    """
    for seg in timeline.segments:
        bars = max(1, min(max_bars, seg.end_bar - seg.start_bar))
        sc = seg.scale
        kind = sc.kind if sc else "메이저"
        events = [(0, seg.chord.root, seg.chord.quality)]
        seg.example = generate_phrase(model, events, kind,
                                      n_bars=bars, seed=seg.idx)["notes"]
    return timeline


if __name__ == "__main__":
    ev = [(0, 2, "m7"), (16, 7, "7")]   # Dm7 → G7 (2마디)
    out = generate_phrase(None, ev, "도리안", n_bars=2, seed=1)
    print("notes:", out["notes"])
