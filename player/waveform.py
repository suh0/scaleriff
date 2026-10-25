"""분석 WAV → 박자 조정 화면용 파형 피크(세션 JSON에 저장, WAV는 지운다)."""
from __future__ import annotations

import wave

import numpy as np

WAVE_RATE = 30   # 초당 파형 컬럼 수(확대 창 300컬럼/10초와 같은 해상도)


def wave_peaks(path: str, rate: int = WAVE_RATE) -> list[list[float]]:
    """PCM16 WAV 전체를 초당 rate개 [min, max]로 요약. 곡별 상위 0.5% 진폭을 ±1로 맞춘다.

    무음은 절대 크기 그대로, 읽기 실패는 [].
    """
    try:
        with wave.open(path, "rb") as f:
            if f.getsampwidth() != 2:
                return []
            sr, ch = f.getframerate(), f.getnchannels()
            samples = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)[::ch]
    except (OSError, wave.Error, EOFError):
        return []
    step = max(1, sr // rate)
    n = len(samples) // step
    if not n:
        return []
    level = float(np.percentile(np.abs(samples[::10].astype(np.int32)), 99.5)) / 32768.0
    if level < 0.05:
        level = 1.0
    c = samples[:n * step].reshape(n, step) / (32768.0 * level)
    return [[round(lo, 3), round(hi, 3)] for lo, hi in
            zip(np.maximum(c.min(1), -1.0).tolist(), np.minimum(c.max(1), 1.0).tolist())]


if __name__ == "__main__":
    import os
    import tempfile
    fd, p = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    with wave.open(p, "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(22050)
        f.writeframes(np.full(22050, 12000, dtype=np.int16).tobytes())
    peaks = wave_peaks(p)
    assert len(peaks) == WAVE_RATE and peaks[0] == [1.0, 1.0], peaks[:2]
    assert wave_peaks("no_such.wav") == []
    os.remove(p)
    print("WAVEFORM OK")
