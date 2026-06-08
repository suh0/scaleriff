"""학습 데이터 준비 — 원천(WJazzD/MIDI) → 토큰 jsonl(2마디 그리드).

출력 한 줄 = {"grid":[32], "qfam":[32], "scale":[32]}  (train_markov 입력)

지원:
  --demo N        : 규칙 기반 합성 N*3개(파이프라인 점검용)
  --wjazzd DB     : Weimar Jazz DB sqlite(wjazzd.db) → 토큰
                    (멜로디 onset/duration/pitch + beats.chord 사용. 16분 그리드 양자화)

WJazzD 주의: 컬럼명은 표준 배포 기준. 버전이 다르면 _read_wjazzd의 쿼리만 맞추면 됨.
실행 예:
  venv\\Scripts\\python.exe -m ml.train.prepare_phrases --demo 200 --out data/phrases.jsonl
  venv\\Scripts\\python.exe -m ml.train.prepare_phrases --wjazzd wjazzd.db --out data/phrases.jsonl
"""
from __future__ import annotations
import argparse
import json
import os

from analyze.theory import parse_chord
from ml.representation import (
    encode, STEPS_PER_BAR, PHRASE_STEPS, quality_family,
)


def _scale_for(qfam: str, region_degs) -> str:
    """코드군→스케일 종류. 마이너는 6도(♮=9 vs ♭=8) 사용빈도로 도리안/마이너 판별."""
    if qfam in ("maj", "dom"):
        return "메이저"
    if qfam == "dim":
        return "마이너"
    nat6 = sum(1 for d in region_degs if d == 9)
    flat6 = sum(1 for d in region_degs if d == 8)
    return "도리안" if nat6 > flat6 else "마이너"


# ── 데모 합성 ────────────────────────────────────────────────────
def demo_examples(n, seed=0):
    from ml.train.make_default_model import build_examples
    ex = build_examples(per_context=max(1, n), seed=seed)
    return ex


# ── WJazzD sqlite → 예제 ─────────────────────────────────────────
def _read_wjazzd(db_path):
    import sqlite3
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    examples = []
    melids = [r[0] for r in con.execute("SELECT DISTINCT melid FROM melody")]
    for melid in melids:
        notes = con.execute(
            "SELECT onset, duration, pitch, bar, beat FROM melody "
            "WHERE melid=? ORDER BY onset", (melid,)).fetchall()
        beats = con.execute(
            "SELECT bar, beat, onset, chord FROM beats "
            "WHERE melid=? ORDER BY onset", (melid,)).fetchall()
        if not notes or not beats:
            continue
        examples.extend(_solo_to_examples(notes, beats))
    con.close()
    return examples


def _solo_to_examples(notes, beats):
    # 마디 시작 시각(beat==1) 수집
    bar_start = {}
    last_chord = {}
    cur_chord = "C"
    for b in beats:
        if b["chord"]:
            cur_chord = b["chord"]
        last_chord[(b["bar"], b["beat"])] = cur_chord
        if b["beat"] == 1:
            bar_start[b["bar"]] = b["onset"]
    bars = sorted(bar_start)
    if len(bars) < 2:
        return []

    def bar_len(bar):
        nxt = bar + 1
        if nxt in bar_start:
            return bar_start[nxt] - bar_start[bar]
        return None

    def chord_at(bar, onset):
        # 같은 마디에서 onset 이하의 가장 최근 비트 코드
        best = None
        for (bb, be), ch in last_chord.items():
            if bb == bar:
                best = best or ch
        return best or "C"

    examples = []
    for k in range(0, len(bars) - 1, 2):           # 2마디 윈도우(비겹침)
        wb = [bars[k], bars[k + 1]]
        if any(bar_len(b) in (None, 0) for b in wb):
            continue
        win_notes, roots, qfams, degs_region = [], [0] * PHRASE_STEPS, ["maj"] * PHRASE_STEPS, []
        for ni, nt in enumerate(notes):
            if nt["bar"] not in wb:
                continue
            bo = wb.index(nt["bar"])
            blen = bar_len(nt["bar"])
            local = (nt["onset"] - bar_start[nt["bar"]]) / blen
            step = bo * STEPS_PER_BAR + int(round(local * STEPS_PER_BAR))
            if not (0 <= step < PHRASE_STEPS):
                continue
            dur_steps = max(1, int(round(nt["duration"] / blen * STEPS_PER_BAR)))
            ch = parse_chord(chord_at(nt["bar"], nt["onset"]))
            win_notes.append((step, dur_steps, nt["pitch"]))
            for s in range(step, min(PHRASE_STEPS, step + dur_steps)):
                roots[s] = ch.root
                qfams[s] = quality_family(ch.quality)
            degs_region.append((nt["pitch"] - ch.root) % 12)
        if len(win_notes) < 4:
            continue
        grid = encode(win_notes, roots, PHRASE_STEPS)
        scales = [_scale_for(qfams[i], degs_region) for i in range(PHRASE_STEPS)]
        examples.append({"grid": grid, "qfam": qfams, "scale": scales})
    return examples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", type=int, help="규칙 기반 합성 개수(컨텍스트당)")
    ap.add_argument("--wjazzd", help="wjazzd.db 경로")
    ap.add_argument("--out", default="data/phrases.jsonl")
    args = ap.parse_args()

    if args.wjazzd:
        examples = _read_wjazzd(args.wjazzd)
    elif args.demo:
        examples = demo_examples(args.demo)
    else:
        ap.error("--demo 또는 --wjazzd 중 하나가 필요합니다")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"[prepare_phrases] {len(examples)}개 프레이즈 → {args.out}")


if __name__ == "__main__":
    main()
