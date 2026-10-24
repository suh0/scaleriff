"""재생 틱 밖에서 음정을 유지한 연습 속도 WAV를 준비한다."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

import imageio_ffmpeg


_CACHE = Path(__file__).resolve().parent.parent / "cache" / "practice_audio"


def validate_rate(rate: float) -> float:
    rate = float(rate)
    if not 0.5 <= rate <= 1.5:
        raise ValueError("연습 속도는 0.5~1.5배여야 해요.")
    return rate


def prepare_audio_rate(source: str, rate: float) -> str:
    """원본 변경 시 캐시를 갱신하며 ffmpeg atempo로 음정을 보존한다."""
    rate = validate_rate(rate)
    original = Path(source).resolve(strict=True)
    if rate == 1.0:
        return str(original)
    stat = original.stat()
    identity = f"{original}|{stat.st_size}|{stat.st_mtime_ns}|{rate:.8g}"
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    _CACHE.mkdir(parents=True, exist_ok=True)
    target = _CACHE / f"{key}.wav"
    if target.is_file() and target.stat().st_size > 44:
        return str(target)
    descriptor, temporary = tempfile.mkstemp(suffix=".wav", dir=_CACHE)
    os.close(descriptor)
    try:
        result = subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error",
            "-y", "-i", str(original), "-vn", "-filter:a", f"atempo={rate:.8g}",
            "-c:a", "pcm_s16le", temporary,
        ], capture_output=True, timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"연습 속도 음원 준비 실패: {detail[-500:]}")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(target)
