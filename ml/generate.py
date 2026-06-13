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
    STEPS_PER_BAR, STEPS_PER_BEAT, quality_family,
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


def _enforce_min_tones(grid, qfams, scale_kind, rng, min_ct=2, min_st=2):
    """리프에 코드톤 ≥min_ct, (코드톤 아닌) 스케일음 ≥min_st 보장 + **골고루 섞기**.

    부족하면 강박 위주 빈 칸에 음을 추가한 뒤, **시간순 온셋에 코드톤·스케일음을
    번갈아(랜덤 위상) 배정** → 앞박=코드톤·뒷박=스케일음 같은 쏠림 없이 교차 배치.
    현재 도수에서 가장 가까운 후보로만 바꿔 윤곽을 유지하고, 스케일 밖 음은 안 만듦.
    """
    deg_pool = sorted(SCALE_DEGREES.get(scale_kind, SCALE_DEGREES["메이저"]))
    qfam = max(set(qfams), key=qfams.count) if qfams else "maj"
    ct_degs = [d for d in deg_pool if d in QFAM_CHORD_TONES.get(qfam, [])] or deg_pool
    st_degs = [d for d in deg_pool if d not in ct_degs] or deg_pool
    n = len(grid)

    # 부족하면 강박(강도 순)부터 음 추가해 최소 (min_ct+min_st)개 확보
    strength = sorted(range(n), key=lambda i: (i % 4 != 0, i % 2 != 0, i))
    need = min_ct + min_st
    onsets = [i for i in range(n) if is_onset(grid[i])]
    for i in strength:
        if len(onsets) >= need:
            break
        if not is_onset(grid[i]):
            grid[i] = onset_token(rng.choice(deg_pool))
            onsets = [k for k in range(n) if is_onset(grid[k])]

    # 시간순 온셋에 코드톤/스케일음 교차 배정(랜덤 위상). 이미 맞으면 안 바꿈.
    onsets = sorted(i for i in range(n) if is_onset(grid[i]))
    start = rng.randint(0, 1)
    for k, i in enumerate(onsets):
        cur = token_degree(grid[i])
        if (k + start) % 2 == 0:             # 코드톤 역할
            if cur not in ct_degs:
                grid[i] = onset_token(_nearest_chord_tone(cur, ct_degs))
        else:                                 # 스케일음 역할
            if cur not in st_degs:
                grid[i] = onset_token(min(st_degs, key=lambda d: abs(d - cur)))
    return grid


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
    grid = _enforce_min_tones(grid, qfams, scale_kind, rng)  # 코드톤·스케일음 ≥2씩
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


def _beat_onsets(count: int, rng: random.Random) -> list[int]:
    """한 박(4칸=16분음표 4칸) 안 온셋 서브스텝 위치. count=음 개수.

    음 길이(온셋 간격)를 다양화하려고 패턴을 여러 가지로 둔다(§2):
      [0,2]=8+8 · [0,1]=16+점8 · [0,3]=점8+16 · [0,1,2]/[0,2,3]/[0,1,3]=16분 조합.
    단음 박([0])은 4분음표(가장 긴 음) → 길이 대비 강조.
    """
    if count <= 1:
        return [0]
    if count == 2:
        return rng.choice([[0, 2], [0, 1], [0, 3]])
    return rng.choice([[0, 1, 2], [0, 2, 3], [0, 1, 3]])


def _assign_tone_roles(n: int, rng: random.Random) -> list[str]:
    """온셋 n개에 코드톤('C')/스케일음('S') 역할 배정(§구성 제약).

    자유롭게 섞되: 스케일음 3연속 금지, 코드톤·스케일음 각각 ≥2개.
    """
    for _ in range(80):
        roles, run_s = [], 0
        for _k in range(n):
            r = "C" if run_s >= 2 else ("S" if rng.random() < 0.5 else "C")
            roles.append(r)
            run_s = run_s + 1 if r == "S" else 0
        if roles.count("C") >= 2 and roles.count("S") >= 2:
            return roles
    return ["C" if i % 2 == 0 else "S" for i in range(n)]   # 폴백


def _pick_class_degree(class_degs, prev_deg, model, qfam, scale_kind,
                       metric, prev_tokens, rng):
    """역할(코드톤/스케일음) 도수 풀에서 음 선택 — 학습 모델 분포 우선, 없으면 스텝모션.

    직전 음과 같은 도수는 후보에서 제외(같은 음 연속 금지 §1).
    """
    pool = [d for d in class_degs if d != prev_deg] or list(class_degs)
    ref = prev_deg if prev_deg is not None else pool[len(pool) // 2]
    if is_trained(model):
        order = getattr(model, "order", 2)
        dist = model.counts(qfam, scale_kind, metric, tuple(prev_tokens[-order:]))
        items = {token_degree(t): c for t, c in dist.items()
                 if is_onset(t) and token_degree(t) in pool}
        if items:
            return _weighted(items, rng)
    return _choose_stepwise(pool, ref, rng)


def generate_scale_riff(model, scale_kind: str, n_bars=1) -> list[dict]:
    """스케일 종류당 1개 리프(루트 0 상대값) — 제어형 생성(§구성).

    리듬: 박마다 2음 이상(단음 박은 마디당 최대 1회).
    음높이: 학습 모델로 도수 선택(폴백 스텝모션). 코드톤·스케일음을 섞되
    스케일음 3연속 금지·각 ≥2개. 대표 quality로 코드톤 컨텍스트.
    """
    rng = random.Random(_kind_seed(scale_kind))
    quality = _KIND_QUALITY.get(scale_kind, "maj7")
    qfam = quality_family(quality)
    deg_pool = sorted(SCALE_DEGREES.get(scale_kind, SCALE_DEGREES["메이저"]))
    ct_degs = [d for d in deg_pool if d in QFAM_CHORD_TONES.get(qfam, [])] or deg_pool
    st_degs = [d for d in deg_pool if d not in ct_degs] or deg_pool
    n_steps = n_bars * STEPS_PER_BAR
    beats_per_bar = STEPS_PER_BAR // STEPS_PER_BEAT

    # 1) 리듬: 박당 음 개수(주로 2, 가끔 3). 단음 박은 마디당 1회까지.
    onset_steps: list[int] = []
    for bar in range(n_bars):
        single_left = 1
        for b in range(beats_per_bar):
            if single_left > 0 and rng.random() < 0.3:
                cnt, single_left = 1, single_left - 1
            else:
                cnt = 2 if rng.random() < 0.7 else 3
            base = bar * STEPS_PER_BAR + b * STEPS_PER_BEAT
            onset_steps += [base + s for s in _beat_onsets(cnt, rng)]
    onset_steps = sorted(set(onset_steps))

    # 2) 톤 역할(코드톤/스케일음 섞기, 스케일음 3연속 금지, 각 ≥2)
    roles = _assign_tone_roles(len(onset_steps), rng)

    # 3) 도수 채우기 + 다음 온셋까지 HOLD(이어지는 라인)
    grid = [REST] * n_steps
    prev_tokens = [BOS] * getattr(model, "order", 2)
    prev_deg = None
    for k, step in enumerate(onset_steps):
        cls = ct_degs if roles[k] == "C" else st_degs
        deg = _pick_class_degree(cls, prev_deg, model, qfam, scale_kind,
                                 step % STEPS_PER_BAR, prev_tokens, rng)
        grid[step] = onset_token(deg)
        prev_deg = deg
        prev_tokens.append(grid[step])
        nxt = onset_steps[k + 1] if k + 1 < len(onset_steps) else n_steps
        for j in range(step + 1, nxt):
            grid[j] = HOLD
            prev_tokens.append(HOLD)

    # 한 옥타브 범위[60,71]로만 디코드 → 모든 음이 한 옥타브 안(§1)
    return decode(grid, [0] * n_steps, prev_midi=60, lo=60, hi=71)


def bake_examples(timeline, model, max_bars=1):
    """빌드 1회: **스케일 종류당 1개** 리프(1마디) 생성(상대값) → 각 구간에 코드
    근음으로 이조 배정(§8). 코드 등장마다가 아니라 종류마다 1개. 코드톤·스케일음을
    각각 2개 이상 포함(§구성 제약). 결과는 timeline.scale_riffs와 seg.example에 저장.
    재생/스크럽 중에는 호출하지 않는다(아키텍처 불변식 §4).
    """
    from ml.representation import SCALE_DEGREES, QFAM_CHORD_TONES, quality_family

    bpb = timeline.time_sig_beats()
    riffs: dict = {}
    for seg in timeline.segments:
        kind = seg.scale.kind if seg.scale else "메이저"
        if kind in riffs:
            continue
        quality = _KIND_QUALITY.get(kind, "maj7")
        qfam = quality_family(quality)
        riffs[kind] = {
            "notes": generate_scale_riff(model, kind, n_bars=max_bars),
            "note_set": sorted(SCALE_DEGREES.get(kind, SCALE_DEGREES["메이저"])),
            "chord_tones": sorted(QFAM_CHORD_TONES.get(qfam, QFAM_CHORD_TONES["maj"])),
            "quality": quality,
            "n_bars": max_bars,
        }
    timeline.scale_riffs = riffs

    # 각 구간: 종류 리프를 코드 근음으로 이조(±6 안쪽) + 구간 길이만큼 **반복 타일링**.
    #   같은 코드가 2마디면 1마디 리프가 두 번 반복된다(§3).
    for seg in timeline.segments:
        kind = seg.scale.kind if seg.scale else "메이저"
        rel = riffs[kind]["notes"]
        riff_beats = max(1, riffs[kind]["n_bars"]) * bpb
        shift = seg.chord.root if seg.chord.root <= 6 else seg.chord.root - 12
        seg_beats = max(1, seg.end_bar - seg.start_bar) * bpb
        ex = []
        t = 0.0
        while t < seg_beats - 1e-6:
            for n in rel:
                if n["beat_pos"] < riff_beats and t + n["beat_pos"] < seg_beats:
                    ex.append({"midi": n["midi"] + shift,
                               "beat_pos": round(t + n["beat_pos"], 4),
                               "dur_beats": n["dur_beats"]})
            t += riff_beats
        seg.example = ex
    return timeline


if __name__ == "__main__":
    ev = [(0, 2, "m7"), (16, 7, "7")]   # Dm7 → G7 (2마디)
    out = generate_phrase(None, ev, "도리안", n_bars=2, seed=1)
    print("notes:", out["notes"])
