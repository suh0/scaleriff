"""오디오 확보 (정의서 §2.2 파이프라인 1단계).

링크(유튜브 등) → yt-dlp로 오디오 추출, 또는 로컬 오디오 파일 허용.
어떤 입력이든 분석용 모노 WAV(고정 SR)로 정규화해 반환한다.

시스템 ffmpeg 없이 동작하도록 imageio-ffmpeg 동봉 바이너리를 사용한다.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import hashlib
import glob
import shutil

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = "ffmpeg"   # PATH 폴백

ANALYZE_SR = 22050   # MIR 분석용 샘플레이트 (librosa 기본)

_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
os.makedirs(_CACHE_DIR, exist_ok=True)


def _is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://") or "youtube.com" in s or "youtu.be" in s


def _cache_key(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]


def _find_deno() -> str | None:
    """PATH 또는 WinGet 설치 위치에서 Deno를 찾는다."""
    if path := shutil.which("deno"):
        return path
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return None
    matches = glob.glob(os.path.join(
        local, "Microsoft", "WinGet", "Packages", "DenoLand.Deno_*", "deno.exe"))
    return sorted(matches)[-1] if matches else None


def to_wav(src_path: str, sr: int = ANALYZE_SR) -> str:
    """임의 오디오 → 모노 WAV(sr). ffmpeg 동봉 바이너리 사용."""
    out = os.path.join(_CACHE_DIR, f"{_cache_key(src_path)}_{sr}.wav")
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    cmd = [FFMPEG, "-y", "-i", src_path, "-ac", "1", "-ar", str(sr),
           "-vn", out]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    return out


def download_audio(url: str, progress_cb=None) -> str:
    """유튜브 등 링크에서 bestaudio 다운로드 → 원본 오디오 경로."""
    import yt_dlp

    key = _cache_key(url)
    outtmpl = os.path.join(_CACHE_DIR, f"dl_{key}.%(ext)s")

    ffmpeg_dir = os.path.dirname(FFMPEG) if os.path.isfile(FFMPEG) else None

    def hook(d):
        if progress_cb and d.get("status") == "downloading":
            pct = 0.0
            if d.get("total_bytes"):
                pct = d["downloaded_bytes"] / d["total_bytes"] * 100
            progress_cb(min(35, 5 + pct * 0.3), "오디오 내려받는 중…")

    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "progress_hooks": [hook],
    }
    if ffmpeg_dir:
        opts["ffmpeg_location"] = ffmpeg_dir
    if deno := _find_deno():
        opts["js_runtimes"] = {"deno": {"path": deno}}

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        # 실제 저장 경로 추정
        ext = info.get("ext", "m4a")
        path = os.path.join(_CACHE_DIR, f"dl_{key}.{ext}")
        if not os.path.exists(path):
            # 확장자 불일치 폴백: dl_{key}.* 탐색
            for f in os.listdir(_CACHE_DIR):
                if f.startswith(f"dl_{key}."):
                    path = os.path.join(_CACHE_DIR, f)
                    break
        title = info.get("title", url)
    return path, title


def resolve_audio(source: str, progress_cb=None) -> tuple[str, str, str]:
    """source(URL 또는 로컬 경로) → (분석용 WAV 경로, 재생용 오디오 경로, 제목).

    재생용은 원본(압축) 그대로, 분석용은 모노 WAV.
    """
    if _is_url(source):
        if progress_cb:
            progress_cb(5, "오디오 확보 중…")
        original, title = download_audio(source, progress_cb)
    else:
        if not os.path.exists(source):
            raise FileNotFoundError(f"파일을 찾을 수 없어요: {source}")
        original = source
        title = os.path.splitext(os.path.basename(source))[0]

    if progress_cb:
        progress_cb(38, "분석용 오디오 변환 중…")
    wav = to_wav(original, ANALYZE_SR)
    return wav, original, title
