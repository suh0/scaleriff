"""리듬+멜로디 공동 표현 — 비트 그리드 토큰 (확정 스펙).

- 한 마디 = 16칸(16분음표), 4/4. 프레이즈 = 2마디 = 32칸.
- 토큰: REST(쉼) · HOLD(앞 음 지속) · ONSET_0..11(코드 근음 기준 도수로 음 시작).
  → onset 위치=리듬, HOLD 길이=음 길이, REST=쉼표, 도수=멜로디(키 독립).
- 음높이는 도수(pitch class 상대)만 학습하고, 디코드 때 직전 음과 가까운
  옥타브로 배치(보이스리딩) → example_phrase {midi, beat_pos, dur_beats}.
- 스윙은 학습/표현에 넣지 않고 재생 단계에서 비율 적용(16칸 직선 유지).
"""
from __future__ import annotations

STEPS_PER_BAR = 16
STEPS_PER_BEAT = 4
BARS_PER_PHRASE = 2
PHRASE_STEPS = STEPS_PER_BAR * BARS_PER_PHRASE

# 토큰 ID
BOS = 0
REST = 1
HOLD = 2
ONSET0 = 3           # ONSET_deg = ONSET0 + deg(0..11)
VOCAB = ONSET0 + 12  # = 15

# 스케일 종류 → 음정 집합(루트 상대 = 도수 집합) / 모드
SCALE_KIND_MODE = {"메이저": "major", "마이너": "minor", "도리안": "dorian"}
SCALE_DEGREES = {
    "메이저": [0, 2, 4, 5, 7, 9, 11],
    "마이너": [0, 2, 3, 5, 7, 8, 10],
    "도리안": [0, 2, 3, 5, 7, 9, 10],
}
# 코드 품질군 → 코드톤 도수(루트 상대)
QFAM_CHORD_TONES = {
    "maj": [0, 4, 7, 11], "dom": [0, 4, 7, 10],
    "min": [0, 3, 7, 10], "dim": [0, 3, 6, 9],
}
# 코드 quality → 품질군
_QUALITY_FAMILY = {
    "maj": "maj", "maj7": "maj", "maj6": "maj", "aug": "maj",
    "dom7": "dom", "7": "dom", "sus4": "dom", "sus2": "dom",
    "min": "min", "m7": "min", "m6": "min",
    "dim": "dim", "dim7": "dim", "m7b5": "dim",
}


def quality_family(quality: str) -> str:
    return _QUALITY_FAMILY.get(quality, "maj")


def onset_token(deg: int) -> int:
    return ONSET0 + (deg % 12)


def is_onset(tok: int) -> bool:
    return tok >= ONSET0


def token_degree(tok: int) -> int:
    return tok - ONSET0


def token_name(tok: int) -> str:
    if tok == BOS:
        return "BOS"
    if tok == REST:
        return "·"
    if tok == HOLD:
        return "—"
    return f"♪{token_degree(tok)}"


# ── 인코드: 음표 리스트 → 그리드 토큰 ────────────────────────────
def encode(notes, chord_roots, n_steps=PHRASE_STEPS) -> list[int]:
    """notes: [(start_step, dur_steps, midi)], chord_roots: 칸별 코드 근음 pc."""
    grid = [REST] * n_steps
    for s, d, m in notes:
        if not (0 <= s < n_steps):
            continue
        root = chord_roots[s] if s < len(chord_roots) else 0
        grid[s] = onset_token((m - root) % 12)
        for j in range(s + 1, min(n_steps, s + max(1, d))):
            if grid[j] == REST:
                grid[j] = HOLD
    return grid


# ── 디코드: 그리드 토큰 → example_phrase ─────────────────────────
def _nearest_midi(pc: int, prev: int, lo: int, hi: int) -> int:
    best, bestd = None, 1e9
    o = (lo // 12) - 1
    while o * 12 + pc <= hi + 12:
        cand = o * 12 + pc
        if lo <= cand <= hi:
            d = abs(cand - prev)
            if d < bestd:
                best, bestd = cand, d
        o += 1
    if best is None:                       # 범위 밖이면 클램프
        best = max(lo, min(hi, (prev // 12) * 12 + pc))
    return best


def decode(grid, chord_roots, prev_midi=67, lo=55, hi=79) -> list[dict]:
    """그리드 → [{midi, beat_pos(박), dur_beats}]. 보이스리딩으로 옥타브 배치."""
    notes, i, n = [], 0, len(grid)
    prev = prev_midi
    while i < n:
        t = grid[i]
        if is_onset(t):
            root = chord_roots[i] if i < len(chord_roots) else 0
            pc = (root + token_degree(t)) % 12
            midi = _nearest_midi(pc, prev, lo, hi)
            prev = midi
            j = i + 1
            while j < n and grid[j] == HOLD:
                j += 1
            notes.append({
                "midi": midi,
                "beat_pos": round(i / STEPS_PER_BEAT, 4),
                "dur_beats": round((j - i) / STEPS_PER_BEAT, 4),
            })
            i = j
        else:
            i += 1
    return notes


def allowed_onset_degrees(scale_kind: str) -> set[int]:
    return set(SCALE_DEGREES.get(scale_kind, SCALE_DEGREES["메이저"]))


if __name__ == "__main__":
    # 라운드트립 점검
    roots = [2] * PHRASE_STEPS                  # D 근음
    notes = [(0, 2, 62), (2, 2, 65), (4, 4, 69), (8, 8, 67)]
    g = encode(notes, roots)
    print("grid:", " ".join(token_name(t) for t in g))
    out = decode(g, roots)
    print("decoded:", out)
