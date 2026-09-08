"""실제 세션 타임라인 빌드 — 전체 파이프라인 1회 굽기 (정의서 §2.2, §4, §5).

  오디오 확보 → MIR(코드/키/BPM/비트·다운비트) → 마디격자(다운비트)·무음경계
  → 구조분석(루프 감지) → 화성분석(코드별 스케일 배정) → Timeline.

코드별 스케일(§3.3): 다이아토닉 → 키의 해당 모드 / 비다이아토닉 → 로컬 코드-스케일.
플레이어는 재생/룩업만(§4). 리프 굽기(§8 bake_examples)는 호출측(gui/app,
regrid)이 Timeline 완성 직후 1회 수행한다.
"""
from __future__ import annotations

from collections import namedtuple

from ingest.audio_source import resolve_audio
from ingest.mir_extract import get_backend
from analyze.structure import analyze_structure, structure_from_grid
from analyze.harmony import analyze_harmony
from analyze.theory import diatonic_option, degree_for
from player.timeline import Timeline, Segment, ScaleOption

_Span = namedtuple("_Span", "start_sec end_sec name")


def _segments_from_structure(st, key_root: int, key_mode: str):
    """구조분석 결과 → 화성분석 → Segment 목록 + 등장 스케일 종류(§3)."""
    harm = analyze_harmony(st.segments, key_root, key_mode, st.loop_len)
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
        wav_ref=wav,                       # 파형 표시용(박자 조정 화면)
    )
    cb(100, "완료")
    return tl


# ── 마디선 보정 (§3.5 2차) — 저장된 코드 스팬으로 재격자화 ──────────────
def regrid_timeline(tl: Timeline, model=None, anchor_sec: float | None = None) -> bool:
    """마디선 보정 — MIR 재실행 없이 구조 재계산만(§3.5 원칙).

    사용자가 드래그로 정한 시작박(anchor_sec)부터 BPM 기반 균등 마디 격자를 깐다
    (마디 길이 = 박자 분자 × 60/BPM). anchor_sec=None이면 현재 첫 마디선 유지
    (박자 전환만 적용). 구조→화성→Segment→리프를 다시 구우므로 수동 코드 수정은
    유실된다. 반환 False = 원자료 없는 구 캐시(보정 불가).

    ponytail: 균등 BPM 격자 — 템포가 흔들리는 곡은 madmom 가변 마디 정보 유실.
    필요해지면 anchor에서 beat_times 스냅으로 업그레이드.
    """
    if not tl.chord_spans or len(tl.bar_times) < 2:
        return False
    duration = tl.bar_times[-1]
    bar_len = tl.time_sig_beats() * tl.beat_sec()
    a = tl.bar_times[0] if anchor_sec is None else max(0.0, anchor_sec)
    if bar_len <= 0 or a >= duration - 1e-3:
        return False
    bars = []
    b = a
    while b < duration - 1e-3:
        bars.append(b)
        b += bar_len
    bars.append(duration)

    spans = [_Span(*c) for c in tl.chord_spans]
    st = structure_from_grid(bars, spans, duration, tl.time_sig_beats())
    key_mode = "minor" if "minor" in (tl.key or "").lower() else "major"
    tl.segments, tl.available_scales = _segments_from_structure(
        st, tl.key_root, key_mode)
    tl.bar_times = st.bar_times
    tl.loop_len = st.loop_len
    tl.loop_phase = st.loop_phase
    from ml.generate import bake_examples   # 지역 import: 무거운 ml 로딩을 보정 시점까지 지연
    bake_examples(tl, model)                 # 새 격자 기준 리프/예시 재굽기(§8)
    return True
