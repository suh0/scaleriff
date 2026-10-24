"""학습 데이터 준비 — WJazzD sqlite → 토큰 jsonl(2마디 그리드).

출력 한 줄 = grid/qfam/scale + solo_id/tune_id/title/performer/instrument.
멜로디 onset/duration/pitch + beats.chord 사용, 16분 그리드 양자화.

WJazzD 주의: 컬럼명은 표준 배포 기준. 버전이 다르면 _read_wjazzd의 쿼리만 맞추면 됨.
실행 예:
  .venv/Scripts/python.exe -m ml.train.prepare_phrases --wjazzd data/wjazzd.db --out cache/phrases_identified.jsonl
"""
from __future__ import annotations
import argparse
import bisect
import json
import os
import re
from pathlib import Path


PREPARATION_VERSION = "wjazzd-tune-v2"

from analyze.theory import parse_chord
from ml.representation import (
    encode, STEPS_PER_BAR, PHRASE_STEPS, quality_family,
)


def _scale_for(qfam: str, region_degs) -> str:
    """코드군→스케일 종류. dom/dim은 모드 정합 라벨(믹솔리디안/로크리안),
    메이저는 4도(#=6 vs ♮=5)로 리디안, 마이너는 2도(♭=1)로 프리지안,
    6도(♮=9 vs ♭=8)로 도리안/마이너 판별 — 실제 사용 음으로 모드 라벨링."""
    if qfam == "maj":
        return "리디안" if region_degs.count(6) > region_degs.count(5) else "메이저"
    if qfam == "dom":
        return "믹솔리디안"
    if qfam == "dim":
        return "로크리안"
    if region_degs.count(1) > region_degs.count(2):
        return "프리지안"
    return "도리안" if region_degs.count(9) > region_degs.count(8) else "마이너"


# ── WJazzD sqlite → 예제 ─────────────────────────────────────────
def _wjazzd_chord(name):
    """Reduce WJazzD's j7/o/- notation and extensions to supported chord qualities."""
    root = re.match(r"^([A-G](?:#|b)?)(.*)$", name.strip())
    if not root:
        return parse_chord(name)
    pitch, suffix = root.groups()
    suffix = suffix.split("/")[0]
    if suffix.startswith("j"):
        suffix = "maj7"
    elif suffix.startswith("o"):
        suffix = "dim7" if "7" in suffix else "dim"
    elif suffix.startswith("-"):
        suffix = "m7" if any(n in suffix for n in ("7", "9", "11", "13")) else (
            "m6" if "6" in suffix else "min")
    elif suffix.startswith("+"):
        suffix = "aug"
    return parse_chord(pitch + suffix)


def _read_wjazzd(db_path):
    import sqlite3
    con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    examples = []
    info = {r["melid"]: dict(r) for r in con.execute("SELECT * FROM solo_info")}
    melids = [r[0] for r in con.execute("SELECT DISTINCT melid FROM melody ORDER BY melid")]
    for melid in melids:
        notes = con.execute(
            "SELECT onset, duration, pitch, bar, beat FROM melody "
            "WHERE melid=? ORDER BY onset", (melid,)).fetchall()
        beats = con.execute(
            "SELECT bar, beat, onset, chord, signature FROM beats "
            "WHERE melid=? ORDER BY onset", (melid,)).fetchall()
        if not notes or not beats:
            continue
        metadata = info.get(melid, {})
        if metadata.get("compid") is None:
            raise ValueError(f"composition ID missing for solo {melid}; tune_id cannot be inferred safely")
        examples.extend(_solo_to_examples(notes, beats, {
            "solo_id": melid, "tune_id": f"wjazzd:composition:{metadata['compid']}",
            "title": metadata.get("title", ""), "performer": metadata.get("performer", ""),
            "instrument": metadata.get("instrument", ""), "source": "WJazzD",
            "preparation_version": PREPARATION_VERSION,
        }))
    con.close()
    return examples


def _solo_to_examples(notes, beats, metadata=None):
    # 마디 시작 시각(beat==1) + 비트별 코드(직전 코드 이월) 수집
    bar_start = {}
    bar_beats, bar_signatures = {}, {}
    beat_onsets, beat_chords = [], []
    cur_chord = "C"
    signature = "4/4"
    for b in beats:
        if b["chord"]:
            cur_chord = b["chord"]
        beat_onsets.append(b["onset"])
        beat_chords.append(cur_chord)
        if "signature" in b.keys() and b["signature"]:
            signature = b["signature"]
        bar_beats.setdefault(b["bar"], set()).add(b["beat"])
        bar_signatures.setdefault(b["bar"], set()).add(signature)
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

    def chord_at(onset):
        # onset 이하의 가장 최근 비트의 코드 — 마디 중간 코드 체인지 반영
        i = bisect.bisect_right(beat_onsets, onset) - 1
        return _wjazzd_chord(beat_chords[i] if i >= 0 else "C")

    examples = []
    for k in range(0, len(bars) - 1, 2):           # 2마디 윈도우(비겹침)
        wb = [bars[k], bars[k + 1]]
        if any(bar_len(b) in (None, 0) for b in wb):
            continue
        # The artifact uses 16 steps/bar. Do not relabel other meters as 4/4 training data.
        if wb[1] != wb[0] + 1 or any(bar_beats[b] != {1, 2, 3, 4} or
                                    bar_signatures[b] != {"4/4"} for b in wb):
            continue
        chords = [chord_at(bar_start[wb[s // STEPS_PER_BAR]] +
                           (s % STEPS_PER_BAR) * bar_len(wb[s // STEPS_PER_BAR]) / STEPS_PER_BAR)
                  for s in range(PHRASE_STEPS)]
        roots = [c.root for c in chords]
        qfams = [quality_family(c.quality) for c in chords]
        win_notes, degs_region = [], {}
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
            ch = chord_at(nt["onset"])
            win_notes.append((step, dur_steps, nt["pitch"]))
            degs_region.setdefault((ch.root, ch.quality), []).append((nt["pitch"] - ch.root) % 12)
        if len(win_notes) < 4:
            continue
        grid = encode(win_notes, roots, PHRASE_STEPS)
        scales = ["디미니시드" if c.quality == "dim7" else "온음" if c.quality == "aug"
                  else _scale_for(qfams[i], degs_region.get((c.root, c.quality), []))
                  for i, c in enumerate(chords)]
        examples.append({"grid": grid, "qfam": qfams, "scale": scales,
                         "start_bar": wb[0], **(metadata or {})})
    return examples


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wjazzd", required=True, help="wjazzd.db 경로")
    ap.add_argument("--out", default="data/phrases.jsonl")
    args = ap.parse_args()
    examples = _read_wjazzd(args.wjazzd)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"[prepare_phrases] {len(examples)}개 프레이즈 → {args.out}")


if __name__ == "__main__":
    main()
