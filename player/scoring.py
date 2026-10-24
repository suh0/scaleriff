"""과제별 참고 점수. 자유 즉흥의 음악적 가치/창의성을 채점하지 않는다."""
from __future__ import annotations

from collections import defaultdict
import numpy as np
from scipy.optimize import linear_sum_assignment


def reference_notes(timeline, start, end):
    notes = []
    for seg in timeline.segments:
        origin = timeline.beat_at(seg.start_sec)
        for n in seg.example:
            sec = timeline.time_at_beat(origin + n["beat_pos"])
            if start <= sec < end:
                finish = timeline.time_at_beat(origin + n["beat_pos"] + n.get("dur_beats", .5))
                notes.append({"midi": n["midi"], "start_sec": sec,
                              "duration_sec": max(0, min(end, finish) - sec), "velocity": 100})
    return sorted(notes, key=lambda n: n["start_sec"])


def target_pc(chord, goal):
    tones = chord.chord_tones()
    if goal == "seventh":
        degree = {"maj7": 11, "m7": 10, "m7b5": 10, "dom7": 10, "7": 10,
                  "dim7": 9}.get(chord.quality)
        return set() if degree is None else {(chord.root + degree) % 12}
    offsets = {"third": (3, 4), "root": (0,)}.get(goal)
    if offsets is None:
        return set(tones)
    return {pc for pc in tones if (pc - chord.root) % 12 in offsets}


def _copy_metrics(tl, actual, expected):
    # 같은 음별 최대 대응 수 → 최소 시간차 할당. 한 기준음을 중복 득점할 수 없다.
    a_by_pitch, e_by_pitch = defaultdict(list), defaultdict(list)
    for n in actual:
        a_by_pitch[n["midi"]].append(n)
    for n in expected:
        e_by_pitch[n["midi"]].append(n)
    pairs = []
    for pitch, refs in e_by_pitch.items():
        played = a_by_pitch[pitch]
        if not played:
            continue
        # 누락 비용은 모든 유효 시간차의 합보다 커야 최대 대응 수가 우선한다.
        cost = np.full((len(refs), len(played) + len(refs)), float(len(refs) + 1))
        for i, ref in enumerate(refs):
            tolerance = max(.04, (tl.time_at_beat(tl.beat_at(ref["start_sec"]) + 1)
                                  - ref["start_sec"]) * .25)
            for j, note in enumerate(played):
                error = abs(note["start_sec"] - ref["start_sec"])
                cost[i, j] = error / tolerance if error <= tolerance else 1e6
        rows, cols = linear_sum_assignment(cost)
        for i, j in zip(rows, cols):
            if j < len(played) and cost[i, j] <= 1:
                pairs.append((refs[i], played[j], cost[i, j]))
    count = len(pairs)
    f1 = 2 * count / (len(actual) + len(expected)) if actual or expected else 0
    rhythm = sum(1 - p[2] for p in pairs) / count if count else 0
    durations = []
    for ref, note, _ in pairs:
        a, b = ref["duration_sec"], note.get("key_duration_sec", note.get("duration_sec", 0))
        durations.append(min(a, b) / max(a, b) if max(a, b) > 0 else 1)
    duration = sum(durations) / count if count else 0
    return {"matched": count, "missing": len(expected) - count, "extra": len(actual) - count,
            "pitch_f1": f1, "rhythm": rhythm, "duration": duration,
            "score": round(100 * f1 * (.7 + .2 * rhythm + .1 * duration), 1)}


def score_performance(timeline, notes, mode="free", level=0, start=0.0, end=None, goal="third"):
    end = timeline.content_end() if end is None else end
    actual = [n for n in notes if start <= n["start_sec"] < end]
    result = {"score": None, "mode": mode, "goal": goal, "sample_count": len(actual),
              "start_sec": start, "end_sec": end, "outside_scale": 0,
              "feedback": "연주 없음", "next_goal": goal, "suggested_density": 1.0}
    if not actual:
        return result
    for note in actual:
        seg = timeline.segment_at(note["start_sec"])
        if seg and note["midi"] % 12 not in seg.note_set:
            result["outside_scale"] += 1
    if mode in ("riff", "practice", "copy"):
        expected = reference_notes(timeline, start, end)
        if not expected:
            result["feedback"] = "비교할 리프가 없습니다"
            return result
        result.update(_copy_metrics(timeline, actual, expected))
        result["feedback"] = (f"리프 모방 {result['score']:.0f}점 · 일치 {result['matched']}/{len(expected)}"
                              f" · 누락 {result['missing']} · 추가 {result['extra']}"
                              f" · 타이밍 {result['rhythm'] * 100:.0f}%")
    else:
        anchors = []
        for seg in timeline.segments:
            if seg.end_sec <= start or seg.start_sec >= end:
                continue
            targets = target_pc(seg.chord, goal)
            if not targets:
                continue  # 없는 7도/3도를 요구하지 않는다.
            # 코드 시작과 유지 중 마디 첫박을 목표로 한다.
            times = {max(start, seg.start_sec)} | {
                t for t in timeline.bar_times if max(start, seg.start_sec) < t < min(end, seg.end_sec)}
            for sec in sorted(times):
                tolerance = max(.04, (timeline.time_at_beat(timeline.beat_at(sec) + 1) - sec) * .25)
                hit = any(n["midi"] >= timeline.split_point and n["midi"] % 12 in targets
                          and abs(n["start_sec"] - sec) <= tolerance for n in actual)
                anchors.append(hit)
        landing = sum(anchors) / len(anchors) if anchors else None
        result.update(landing_hits=sum(anchors), landing_targets=len(anchors), landing=landing)
        if mode == "scale":
            hits = 0
            for n in actual:
                seg = timeline.segment_at(n["start_sec"])
                if not seg:
                    continue
                left = n["midi"] < timeline.split_point
                pool = ({seg.chord.root} if left and level in (1, 2) else
                        set(seg.chord_tones()) if left or level == 1 else set(seg.note_set))
                hits += n["midi"] % 12 in pool
            result["target_ratio"] = hits / len(actual)
            total = result["target_ratio"] if landing is None else .6 * result["target_ratio"] + .4 * landing
            result["score"] = round(100 * total, 1)
            landing_text = f"착지 {sum(anchors)}/{len(anchors)}" if anchors else "선택한 착지음 없음 · 목표음만 평가"
            result["feedback"] = f"스케일 과제 {result['score']:.0f}점 · 목표음 {hits}/{len(actual)} · {landing_text}"
        elif landing is not None:
            result["score"] = round(100 * landing, 1)
            result["feedback"] = f"착지 과제 {result['score']:.0f}점 · {sum(anchors)}/{len(anchors)}회 · 경과음은 감점하지 않음"
        else:
            result["feedback"] = "이 구간에는 선택한 착지음이 없습니다. 코드톤 목표를 선택하세요"
    if result["score"] is not None:
        if result["score"] < 70:
            result["suggested_density"] = .75
            result["feedback"] += " · 다음: 음 수를 줄여 같은 목표 반복"
        else:
            result["next_goal"] = "seventh" if goal == "third" else "third"
            result["feedback"] += " · 다음: 착지음 또는 리듬을 바꿔 변주"
    result["density"] = len(actual) / max(1, timeline.beats_between(start, end))
    return result
