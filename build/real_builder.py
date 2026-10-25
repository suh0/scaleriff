"""실제 세션 타임라인 빌드 — 전체 파이프라인 1회 굽기 (정의서 §2.2, §4, §5).

  오디오 확보 → MIR(코드/키/BPM/비트·다운비트) → 마디격자(다운비트)·무음경계
  → 구조분석(루프 감지) → 화성분석(코드별 스케일 배정) → Timeline.

코드별 스케일(§3.3): 다이아토닉 → 키의 해당 모드 / 비다이아토닉 → 로컬 코드-스케일.
플레이어는 재생/룩업만(§4). 리프는 메인 화면 리프학습모드에서만 만든다
(ml.generate.bake_progression).
"""
from __future__ import annotations

from collections import namedtuple
import bisect

from ingest.audio_source import resolve_audio
from ingest.mir_extract import get_backend
from analyze.structure import analyze_structure, structure_from_grid
from analyze.harmony import analyze_harmony
from analyze.theory import diatonic_option, degree_for
from player.timeline import Timeline, Segment, ScaleOption
from player.waveform import wave_peaks

_Span = namedtuple("_Span", "start_sec end_sec name")


def _segments_from_structure(st, key_root: int, key_mode: str, fixed_key: bool = False):
    """구조분석 결과 → 화성분석 → Segment 목록 + 등장 스케일 종류(§3)."""
    harm = analyze_harmony(st.segments, key_root, key_mode, st.loop_len, fixed_key)
    segments: list[Segment] = []
    available: list[str] = []
    for i, h in enumerate(harm):
        o = diatonic_option(h.chord, h.home_root, h.home_mode, h.is_detour, h.note_set)
        cands = [ScaleOption(o["kind"], o["root"], o["name"], o["note_set"])]
        if o["kind"] not in available:
            available.append(o["kind"])
        segments.append(Segment(
            idx=i, start_sec=h.raw.start_sec, end_sec=h.raw.end_sec,
            start_bar=h.raw.start_bar, end_bar=h.raw.end_bar,
            chord=h.chord, candidates=cands, active=0,
            degree=degree_for(h.chord, key_root), is_detour=h.is_detour,
        ))
    return segments, available


def _structure_with_preroll(bars, spans, duration, beats, chord_end=None):
    """음수 마디는 번호만 남기고 코드/리프 구간에서는 제외한다.

    chord_end(마디선)가 있으면 그 뒤 마디도 코드/리프 없이 마디선만 둔다.
    """
    first = next(i for i in range(len(bars) - 1) if bars[i + 1] > 0)
    last = len(bars) - 1
    if chord_end is not None:
        last = min(last, max(first + 1, bisect.bisect_left(bars, chord_end - 1e-6)))
        duration = min(duration, bars[last]) if last < len(bars) - 1 else duration
    st = structure_from_grid(bars[first:last + 1], spans, duration, beats)
    for seg in st.segments:
        seg.start_bar += first
        seg.end_bar += first
        seg.start_sec = max(0.0, seg.start_sec)
    st.bar_times = bars
    st.loop_phase += first
    return st


def build_real_timeline(source: str, progress_cb=None) -> Timeline:
    def cb(p, m):
        if progress_cb:
            progress_cb(int(p), m)

    # 1) 오디오 확보 (§2)
    wav, playback_path, title = resolve_audio(source, cb)

    # 2) MIR — 코드/키/BPM/비트·다운비트/무음경계 (madmom 설치 시 학습 모델 자동 사용)
    backend = get_backend()
    mir = backend.analyze(wav, progress_cb=cb)

    # 3) 구조 분석 — 다운비트 마디격자/루프 감지
    cb(78, "구조 분석(루프 감지)…")
    st = analyze_structure(mir)
    time_sig = f"{st.beats_per_bar}/4"
    key_root = mir.key_root or 0

    # 4~5) 화성 분석 + Segment 생성 — 코드별 단일 다이아토닉 스케일/도수(§3)
    cb(85, "화성 분석(코드별 스케일 배정)…")
    segments, available = _segments_from_structure(
        st, key_root, mir.key_mode or "major")

    cb(99, "세션 타임라인 굽기…")
    tl = Timeline(
        audio_ref=playback_path, bpm=round(mir.bpm, 1), time_sig=time_sig,
        key=mir.key or "C major", key_root=key_root, loop_len=st.loop_len,
        segments=segments, available_scales=available, title=title,
        content_span=mir.content_span,
        bar_times=st.bar_times, loop_phase=st.loop_phase,
        beat_times=list(mir.beat_times),   # 마디선 보정(§3.5 2차) 재료
        chord_spans=[[c.start_sec, c.end_sec, c.name] for c in mir.chords],
        wave_peaks=wave_peaks(wav),        # 파형 표시용(박자 조정 화면) — 분석 WAV는 이후 삭제
        analysis_info={"beat_backend": mir.beat_source,
                       "beat_detected": mir.beat_detected,
                       "chord_backend": "madmom" if backend.use_madmom else "librosa",
                       "chord_vocabulary": "maj/min", "estimated": True},
    )
    cb(100, "완료")
    return tl


# ── 마디선 보정 (§3.5 2차) — 저장된 코드 스팬으로 재격자화 ──────────────
def regrid_timeline(tl: Timeline, anchor_sec: float | None = None,
                    preserve_tempo: bool = False, bars: list[float] | None = None) -> bool:
    """마디선 보정 — MIR 재실행 없이 구조 재계산만(§3.5 원칙).

    사용자가 드래그로 정한 시작박(anchor_sec)부터 BPM 기반 균등 마디 격자를 깐다
    (마디 길이 = 박자 분자 × 60/BPM). anchor_sec=None이면 현재 첫 마디선 유지
    (박자 전환만 적용). 수동 코드는 원본 시간 기반 오버라이드로 재적용한다.
    preserve_tempo=True는 시작점만 옮길 때 가변 마디 간격을 보존한다.
    bars를 주면 그 마디 시작 목록(곡 끝 미포함)을 그대로 쓴다(박자 화면의 검출 비트 격자).
    """
    if not tl.chord_spans or len(tl.bar_times) < 2:
        return False
    duration = tl.bar_times[-1]
    bar_len = tl.time_sig_beats() * tl.beat_sec()
    a = tl.bar_times[0] if anchor_sec is None else anchor_sec
    if bar_len <= 0 or a >= duration - 1e-3:
        return False
    for lp in tl.loops:
        if "start_sec" not in lp and 0 <= lp["start_bar"] < lp["end_bar"] + 1 < len(tl.bar_times):
            lp["start_sec"] = tl.bar_times[lp["start_bar"]]
            lp["end_sec"] = tl.bar_times[lp["end_bar"] + 1]
    if bars is not None:
        bars = [b for b in bars if b < duration - 1e-3]
        if not bars:
            return False
    elif preserve_tempo:
        delta = a - tl.bar_times[0]
        bars = [t + delta for t in tl.bar_times[:-1] if t + delta < duration - 1e-3]
    else:
        bars = []
        b = a
        while b < duration - 1e-3:
            bars.append(b)
            b += bar_len
        tl.timing_override = True
    bars.append(duration)

    spans = [_Span(*c) for c in tl.effective_chord_spans()]
    # 오디오 이전의 마디에는 코드/리프를 만들지 않는다. 마디 번호는 유지한다.
    st = _structure_with_preroll(bars, spans, duration, tl.time_sig_beats(), tl.chord_end)
    key_mode = "minor" if "minor" in (tl.key or "").lower() else "major"
    tl.segments, tl.available_scales = _segments_from_structure(
        st, tl.key_root, key_mode, fixed_key=tl.key_override)
    tl.bar_times = st.bar_times
    tl.loop_len = st.loop_len
    tl.loop_phase = st.loop_phase
    for lp in tl.loops:
        if "start_sec" in lp:
            lp["start_bar"] = max(0, bisect.bisect_right(bars, lp["start_sec"]) - 1)
            lp["end_bar"] = min(len(bars) - 2, max(lp["start_bar"],
                                                  bisect.bisect_left(bars, lp["end_sec"]) - 1))
    return True


def apply_chord_edit(tl: Timeline, start: float, end: float, name: str):
    """선택한 실제 시간 구간만 보정하고 원시 MIR 결과는 유지한다."""
    if not tl.chord_spans:
        tl.chord_spans = [[s.start_sec, s.end_sec, s.chord.name] for s in tl.segments]
    if len(tl.bar_times) < 2:
        length = tl.beat_sec() * tl.time_sig_beats()
        tl.bar_times = [i * length for i in range(tl.total_bars() + 1)]
    tl.chord_overrides.append([start, end, name])
    st = _structure_with_preroll(tl.bar_times, [_Span(*c) for c in tl.effective_chord_spans()],
                               tl.bar_times[-1], tl.time_sig_beats(), tl.chord_end)
    mode = "minor" if "minor" in tl.key.lower() else "major"
    tl.segments, tl.available_scales = _segments_from_structure(st, tl.key_root, mode, True)
