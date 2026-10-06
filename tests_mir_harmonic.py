"""MIR의 HPSS 중복 제거와 콘텐츠 경계 결과 유지 검증."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import librosa
import numpy as np
import soundfile as sf

from ingest.mir_extract import MirBackend, detect_content_span


def main():
    sr = 22050
    t = np.arange(sr * 4) / sr
    y = (0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    y[:sr] = 0
    y[-sr:] = 0
    with TemporaryDirectory() as directory:
        path = Path(directory) / "audio.wav"
        sf.write(path, y, sr, subtype="FLOAT")
        with patch("librosa.effects.harmonic", wraps=librosa.effects.harmonic) as harmonic:
            result = MirBackend(use_madmom=False).analyze(str(path))
        assert harmonic.call_count == 1, f"HPSS 호출 횟수: {harmonic.call_count}"

    kwargs = dict(downbeat_times=result.downbeat_times, chords=result.chords,
                  bar_sec=result.beats_per_bar * 60 / result.bpm, log=lambda _: None)
    standalone = detect_content_span(y, sr, len(y) / sr, **kwargs)
    y_harm = librosa.effects.harmonic(y, margin=2.0)
    with patch("librosa.effects.harmonic", side_effect=AssertionError("HPSS 재계산")):
        reused = detect_content_span(y, sr, len(y) / sr, y_harm=y_harm, **kwargs)
    assert reused == standalone == result.content_span
    print("MIR HARMONIC OK")


if __name__ == "__main__":
    main()
