"""MIR 파이프라인 검증 — 알려진 진행을 합성해 코드/키/BPM 추출 정확도 확인."""
import os, sys
os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import soundfile as sf
from analyze.theory import parse_chord
from ingest.mir_extract import get_backend

SR = 22050
BPM = 100
BEAT = 60.0 / BPM
BAR = BEAT * 4


def synth_chord(midis, dur, sr=SR):
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    y = np.zeros_like(t)
    for m in midis:
        f = 440.0 * 2 ** ((m - 69) / 12)
        # 기음 + 약한 배음
        y += np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)
    # 어택/릴리즈 엔벨로프
    env = np.ones_like(t)
    a = int(sr * 0.02)
    env[:a] = np.linspace(0, 1, a)
    env[-a:] = np.linspace(1, 0, a)
    return y * env / max(1, len(midis))


def main():
    prog = ["C", "Am", "F", "G"]      # C major, 각 1마디, 2회 반복
    chord_midis = {
        "C": [60, 64, 67], "Am": [57, 60, 64],
        "F": [53, 57, 60], "G": [55, 59, 62],
    }
    audio = []
    for _ in range(2):
        for name in prog:
            audio.append(synth_chord(chord_midis[name], BAR))
    y = np.concatenate(audio)
    path = os.path.join(os.path.dirname(__file__), "cache", "synth_test.wav")
    sf.write(path, y, SR)
    print(f"synth: {len(prog)*2} bars, {len(y)/SR:.1f}s -> {path}")

    backend = get_backend("librosa")
    res = backend.analyze(path)
    print(f"\nBPM={res.bpm:.1f} (expected {BPM})")
    print(f"KEY={res.key} (expected C major)")
    print(f"chords ({len(res.chords)}):")
    for c in res.chords:
        print(f"  {c.start_sec:5.1f}-{c.end_sec:5.1f}s  {c.name}")


if __name__ == "__main__":
    main()
