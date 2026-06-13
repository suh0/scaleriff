"""더미 타임라인 — 오디오 없이 플레이어·악보 UI를 둘러보는 데모(§6 [0]).

C major ii–V–I 루프(Dm7–G7–Cmaj7) ×2 = 6마디. 코드별 단일 다이아토닉 스케일
(D 도리안 / G 믹솔리디안 / C 아이오니안). 한 코드=한 스케일이라 선택 불가(§3). 오디오 없음.
"""
from __future__ import annotations

from analyze.theory import parse_chord, diatonic_option, degree_for, scale_pcs
from player.timeline import Timeline, Segment, ScaleOption


def build_dummy_timeline() -> Timeline:
    bpm = 100.0
    bar = (60.0 / bpm) * 4
    key_root = 0
    home_set = scale_pcs(key_root, "major")   # C 메이저 7음 — 전 구간 다이아토닉

    chord_names = ["Dm7", "G7", "Cmaj7"]
    loop_len = len(chord_names)

    segments: list[Segment] = []
    available: list[str] = []
    b = 0
    for _rep in range(2):
        for cname in chord_names:
            chord = parse_chord(cname)
            o = diatonic_option(chord, key_root, "major", False, home_set)
            cands = [ScaleOption(o["kind"], o["root"], o["name"], o["note_set"])]
            if o["kind"] not in available:
                available.append(o["kind"])
            segments.append(Segment(
                idx=b, start_sec=round(b * bar, 3), end_sec=round((b + 1) * bar, 3),
                start_bar=b, end_bar=b + 1, chord=chord,
                candidates=cands, active=0, degree=degree_for(chord, key_root),
            ))
            b += 1

    duration = segments[-1].end_sec
    return Timeline(
        audio_ref="", bpm=bpm, time_sig="4/4", key="C major", key_root=key_root,
        loop_len=loop_len, segments=segments, available_scales=available,
        title="(데모) ii–V–I 스케일 연습", content_span=(0.0, duration),
    )


if __name__ == "__main__":
    tl = build_dummy_timeline()
    print(f"{tl.title} | {tl.key} | 종류={tl.available_scales}")
    for s in tl.segments[:3]:
        print(f"  [{s.idx}] {s.chord.name:6} {s.degree:4} 후보="
              f"{[c.name for c in s.candidates]}")
