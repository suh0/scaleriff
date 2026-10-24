"""화성 분석 (정의서 §3.3) — 코드별 스케일(note_set) 결정.

- 다이아토닉: 코드 구성음이 한 키의 홈 스케일 안에 들면 다이아토닉.
- note_set 결정:
  · 다이아토닉 진행 → 키의 홈 스케일을 동일 적용(안전 지도)
  · 비다이아토닉 고립(1~2개) → 그 구간만 코드-스케일(로컬 디투어) 후 홈 복귀
  · 전조: 새 키에 2개 이상 연속 일관 → 홈 스케일 전환. 키 재평가는 루프 단위로.
- note_set은 피아노 가이드 배지·채점 게이트(§7.5)·리프 스케일 게이트(§8)의 공통 기준.
"""
from __future__ import annotations

from dataclasses import dataclass

from analyze.theory import parse_chord, scale_pcs, Chord
from analyze.structure import RawSegment


@dataclass
class HarmonizedSegment:
    raw: RawSegment
    chord: Chord
    note_set: list[int]      # pitch class 0~11
    home_root: int           # 이 구간에 적용된 홈 키 root
    home_mode: str           # "major" | "minor"
    is_detour: bool          # 비다이아토닉 로컬 디투어 여부


def _is_diatonic(chord: Chord, scale: set[int]) -> bool:
    return all(pc in scale for pc in chord.chord_tones())


def _best_key_for_chords(chords: list[Chord], prefer: tuple[int, str] | None = None):
    """코드 집합에 가장 잘 맞는 키(root, mode). prefer가 동률이면 유지(히스테리시스)."""
    best_fit, best = -1, (0, "major")
    prefer_fit = -1
    for root in range(12):
        for mode in ("major", "minor"):
            scale = set(scale_pcs(root, mode))
            fit = 0
            for c in chords:
                fit += sum(1 for pc in c.chord_tones() if pc in scale)
            if prefer and (root, mode) == prefer:
                prefer_fit = fit
            if fit > best_fit:
                best_fit, best = fit, (root, mode)
    # 현재 키가 최선과 1점 이내면 유지(전조 과민 방지)
    if prefer and prefer_fit >= best_fit - 1:
        return prefer
    return best


def analyze_harmony(segments: list[RawSegment], key_root: int, key_mode: str,
                    loop_len: int, fixed_key: bool = False) -> list[HarmonizedSegment]:
    chords = [parse_chord(s.chord_name) for s in segments]

    # 루프 단위로 홈 키 재평가 (§5.3 전조)
    seg_home: list[tuple[int, str]] = [None] * len(segments)
    current_key = (key_root, key_mode)
    # 마디 → 세그먼트 매핑으로 루프 경계 판단
    loop = max(1, loop_len)
    # 각 세그먼트가 속한 루프 인덱스 (start_bar 기준)
    for li_start in range(0, _max_bar(segments), loop):
        idxs = [i for i, s in enumerate(segments)
                if li_start <= s.start_bar < li_start + loop]
        if not idxs:
            continue
        loop_chords = [chords[i] for i in idxs]
        if not fixed_key:
            current_key = _best_key_for_chords(loop_chords, prefer=current_key)
        for i in idxs:
            seg_home[i] = current_key
    # 매핑 안 된 세그먼트 보정
    for i in range(len(segments)):
        if seg_home[i] is None:
            seg_home[i] = current_key

    # note_set 결정 + 비다이아토닉 고립 디투어
    result: list[HarmonizedSegment] = []
    for i, (seg, chord) in enumerate(zip(segments, chords)):
        hroot, hmode = seg_home[i]
        home_scale = set(scale_pcs(hroot, hmode))
        if _is_diatonic(chord, home_scale):
            note_set = sorted(home_scale)
            detour = False
        else:
            # 비다이아토닉 → 로컬 코드-스케일 디투어(§5.3)
            note_set = sorted(set(chord.chord_scale()) | set(chord.chord_tones()))
            detour = True
        result.append(HarmonizedSegment(
            raw=seg, chord=chord, note_set=note_set,
            home_root=hroot, home_mode=hmode, is_detour=detour,
        ))
    return result


def _max_bar(segments: list[RawSegment]) -> int:
    return max((s.end_bar for s in segments), default=1)
