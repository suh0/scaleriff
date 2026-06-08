"""구조+화성 분석 검증 (synth_test.wav 사용; 없으면 tests_mir 먼저 실행)."""
import os, sys
os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingest.mir_extract import get_backend
from analyze.structure import analyze_structure
from analyze.harmony import analyze_harmony
from analyze.theory import pc_name

WAV = os.path.join(os.path.dirname(__file__), "cache", "synth_test.wav")


def main():
    if not os.path.exists(WAV):
        print("synth_test.wav 없음 — tests_mir.py 먼저 실행")
        return
    mir = get_backend("librosa").analyze(WAV)
    st = analyze_structure(mir, "4/4")
    print(f"bars={len(st.per_bar_chord)}  loop_len={st.loop_len}  "
          f"harmonic_rhythm={st.harmonic_rhythm:.1f}")
    print("per_bar:", st.per_bar_chord)
    print(f"raw segments ({len(st.segments)}):")
    for s in st.segments:
        print(f"  bar{s.start_bar}-{s.end_bar} {s.start_sec:5.1f}-{s.end_sec:5.1f}s {s.chord_name}")

    harm = analyze_harmony(st.segments, mir.key_root, mir.key_mode, st.loop_len)
    print(f"\nkey={mir.key}  harmonized ({len(harm)}):")
    for h in harm:
        ns = [pc_name(p) for p in h.note_set]
        tag = " [detour]" if h.is_detour else ""
        print(f"  {h.chord.name:6} home={pc_name(h.home_root)} {h.home_mode:6} "
              f"note_set={ns}{tag}")


if __name__ == "__main__":
    main()
