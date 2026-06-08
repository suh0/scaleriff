"""세션 타임라인 빌더 라우터 (정의서 §2, §4).

source가 있으면 실제 파이프라인, 비면 데모 타임라인.
진행 콜백 signature: cb(percent: int, message: str)
"""
from __future__ import annotations

from player.timeline import Timeline
from player.dummy_timeline import build_dummy_timeline


def build_timeline(source: str, progress_cb=None) -> Timeline:
    def cb(p, m):
        if progress_cb:
            progress_cb(p, m)

    if not source:
        cb(10, "데모 타임라인 준비 중")
        tl = build_dummy_timeline()
        cb(100, "완료")
        return tl

    cb(5, "오디오 확보 중…")
    from ml.real_builder import build_real_timeline
    return build_real_timeline(source, cb)
