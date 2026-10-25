"""재생 틱 밖에서 음정을 유지한 연습 속도 WAV를 준비한다."""
from __future__ import annotations

import atexit
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

import imageio_ffmpeg


# 실행 중에만 쓰는 임시 폴더 — 앱 종료 시 삭제(속도 변환 결과를 남기지 않는다).
# ponytail: 비정상 종료 시엔 OS 임시 폴더에 남음, 필요하면 시작 시 이전 scaleriff_rate_* 정리
_CACHE = Path(tempfile.mkdtemp(prefix="scaleriff_rate_"))
atexit.register(shutil.rmtree, _CACHE, ignore_errors=True)


def validate_rate(rate: float) -> float:
    rate = float(rate)
    if not 0.5 <= rate <= 1.5:
        raise ValueError("연습 속도는 0.5~1.5배여야 해요.")
    return rate


def prepare_audio_rate(source: str, rate: float) -> str:
    """ffmpeg atempo로 음정을 보존한다. 같은 실행 안에서는 결과를 재사용한다."""
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
