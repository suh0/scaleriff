"""더미 타임라인 — 오디오 없이 플레이어·악보 UI를 둘러보는 데모(§6 [0]).

C major ii–V–I 루프(Dm7–G7–Cmaj7) ×2 = 6마디. 각 구간에 후보 스케일:
모드(D 도리안 / G 믹솔리디안 / C 아이오니안) + 펜타토닉. 오디오 없음.
"""
from __future__ import annotations

from analyze.theory import parse_chord, scale_options, degree_for
from player.timeline import Timeline, Segment, ScaleOption


def build_dummy_timeline() -> Timeline:
    bpm = 100.0
    bar = (60.0 / bpm) * 4
    key_root = 0

    chord_names = ["Dm7", "G7", "Cmaj7"]
    loop_len = len(chord_names)

    segments: list[Segment] = []
    available: list[str] = []
    b = 0
    for _rep in range(2):
        for cname in chord_names:
            chord = parse_chord(cname)
            opts = scale_options(chord)
            cands = [ScaleOption(o["kind"], o["root"], o["name"], o["note_set"]) for o in opts]
            for o in opts:
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
