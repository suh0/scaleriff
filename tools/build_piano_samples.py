"""Salamander Grand Piano(CC BY 3.0, Alexander Holm) v10 샘플 30개 → assets/piano/{21..108}.flac.

원본은 A0부터 단3도 간격 녹음이라 사이 음은 가장 가까운 샘플을 ±1반음 리샘플한다.
사용: python tools/build_piano_samples.py <SalamanderGrandPiano/Samples 폴더>
원본: https://github.com/sfzinstruments/SalamanderGrandPiano
"""
import os
import sys
from fractions import Fraction

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SR = 44100
DUR = 6.0   # player.note_synth.NOTE_DUR과 같게
NAMES = ["A", "C", "D#", "F#"]   # 21+3k 순서(A0, C1, D#1, F#1, A1, ...)
# 원본 sfz Data/tune_ret.txt의 샘플별 보정(cent) — 고음일수록 녹음이 높게 조율돼 있다
TUNE = [10, 13, 11, -3, -9, -9, -11, -7, -4, 0, -6, -3, -3, -6, -3, 0, -4, -8, -8, -5,
        -7, -8, -12, -13, -12, -17, -17, -27, -38, -38]
TOP_ROOT = 105   # C8 샘플은 실측 ~4434Hz(+1반음)로 어긋나 A7까지만 쓴다
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "assets", "piano")


def sample_name(root: int) -> str:
    k = (root - 21) // 3
    return f"{NAMES[k % 4]}{(root - 12) // 12}v10.flac"   # A0=21, C1=24 ...


def render(src_dir: str, midi: int) -> np.ndarray:
    root = min(TOP_ROOT, 21 + 3 * round((midi - 21) / 3))
    x, sr = sf.read(os.path.join(src_dir, sample_name(root)), dtype="float64")
    x = x.mean(axis=1) if x.ndim == 2 else x
    cents = (midi - root) * 100 + TUNE[(root - 21) // 3]
    # 음을 2^(c/1200)배 높이면서 sr → SR: 출력 길이 비율 = SR / sr / 2^(c/1200)
    ratio = Fraction(SR / sr / 2 ** (cents / 1200)).limit_denominator(2000)
    y = resample_poly(x, ratio.numerator, ratio.denominator)
    onset = int(np.argmax(np.abs(y) > 0.02 * np.max(np.abs(y))))
    y = y[max(0, onset - int(0.002 * SR)):][:int(DUR * SR)]   # 앞 무음 제거(2ms 여유)
    fade = int(0.3 * SR)
    y[-fade:] *= np.linspace(1.0, 0.0, fade)
    return y / np.max(np.abs(y)) * 0.75


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for m in range(21, 109):
        sf.write(os.path.join(OUT, f"{m}.flac"), render(sys.argv[1], m), SR, subtype="PCM_16")
    print("ok", OUT)
