"""실제 세션 타임라인 빌드 — 전체 파이프라인 1회 굽기 (정의서 §2, §4, §5).

  오디오 확보 → MIR(코드/키/BPM/비트·다운비트) → 마디격자(다운비트)·무음경계
  → 구조분석(루프 감지) → 화성분석(코드별 스케일 배정) → Timeline.

코드별 스케일(§3): 다이아토닉 → 키의 해당 모드 / 비다이아토닉 → 로컬 코드-스케일.
플레이어는 재생/룩업만(§4). ML 예시 생성은 현재 범위 제외(추후 §8).

NOTE: 패키지 이름은 ml/ 그대로 두되(추후 §8 예시 생성 재도입 지점), 지금은 ML 미사용.
"""
from __future__ import annotations

from ingest.audio_source import resolve_audio
from ingest.mir_extract import get_backend
from analyze.structure import analyze_structure
from analyze.harmony import analyze_harmony
from analyze.theory import diatonic_option, degree_for
from player.timeline import Timeline, Segment, ScaleOption


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

    # 4) 화성 분석 — 코드별 홈 키/디투어/note_set (§3)
    cb(85, "화성 분석(코드별 스케일 배정)…")
    harm = analyze_harmony(st.segments, key_root,
                           mir.key_mode or "major", st.loop_len)

    # 5) Segment 생성 — 코드별 단일 다이아토닉 스케일/도수 부여, 등장 종류 집계
    #    7다이아토닉 모드에서 한 코드 = 한 스케일 → 후보 1개(선택 불가, §3)
    cb(92, "스케일 배정/집계…")
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

    cb(99, "세션 타임라인 굽기…")
    tl = Timeline(
        audio_ref=playback_path, bpm=round(mir.bpm, 1), time_sig=time_sig,
        key=mir.key or "C major", key_root=key_root, loop_len=st.loop_len,
        segments=segments, available_scales=available, title=title,
        content_span=mir.content_span,
    )
    cb(100, "완료")
    return tl
