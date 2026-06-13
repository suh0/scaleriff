"""세션 타임라인 — 스케일 트레이너 스키마 (정의서 §5, 후보 스케일 확장).

원칙(§4): 모든 분석은 빌드 단계에서 한 번에 구워(pre-bake) 이 타임라인을 만들고,
플레이어는 재생/룩업만 한다. 재생/스크럽 중 재분석 없음.

각 코드 구간(Segment)은 **여러 후보 스케일(candidates)**을 갖고, active 인덱스로
실제 적용 스케일을 고른다. 악보 화면에서 마디별로 사용자가 바꿀 수 있다.
ML 예시(example_phrase)는 현재 범위 제외(추후 §8).
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json

from analyze.theory import Chord


@dataclass
class ScaleOption:
    """후보 스케일 하나."""
    kind: str                  # 종류 이름(예 "도리안", "메이저 펜타토닉")
    root: int                  # 스케일 시작음 pc (도수 계산용)
    name: str                  # 표시명(예 "D 도리안")
    note_set: list[int]        # pitch class 0~11

    def to_dict(self):
        return {"kind": self.kind, "root": self.root,
                "name": self.name, "note_set": list(self.note_set)}

    @staticmethod
    def from_dict(d):
        return ScaleOption(d["kind"], d["root"], d["name"], list(d["note_set"]))


@dataclass
class Segment:
    """코드 지속 구간 — 코드 + 후보 스케일들(active 선택)."""
    idx: int
    start_sec: float
    end_sec: float
    start_bar: int
    end_bar: int
    chord: Chord
    candidates: list[ScaleOption] = field(default_factory=list)
    active: int = 0
    degree: str = ""           # 키 기준 코드 도수(예 "ii") — 악보 표시용
    is_detour: bool = False     # 비다이아토닉(로컬 코드-스케일) 구간 여부 §3
    example: list = field(default_factory=list)  # ML 생성 예시 [{midi,beat_pos,dur_beats}]

    # ── 활성 스케일 헬퍼 ────────────────────────────────────────
    @property
    def scale(self) -> ScaleOption | None:
        if not self.candidates:
            return None
        i = self.active if 0 <= self.active < len(self.candidates) else 0
        return self.candidates[i]

    @property
    def note_set(self) -> list[int]:
        s = self.scale
        return s.note_set if s else []

    @property
    def scale_name(self) -> str:
        s = self.scale
        return s.name if s else ""

    @property
    def scale_root(self) -> int:
        s = self.scale
        return s.root if s else self.chord.root

    def chord_tones(self) -> list[int]:
        return self.chord.chord_tones()

    def has_options(self) -> bool:
        return len(self.candidates) > 1

    def set_active_by_kind(self, kind: str) -> bool:
        for i, c in enumerate(self.candidates):
            if c.kind == kind:
                self.active = i
                return True
        return False

    def duration(self) -> float:
        return self.end_sec - self.start_sec

    def to_dict(self):
        return {
            "idx": self.idx,
            "start_sec": self.start_sec, "end_sec": self.end_sec,
            "start_bar": self.start_bar, "end_bar": self.end_bar,
            "chord": self.chord.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "active": self.active, "degree": self.degree,
            "is_detour": self.is_detour,
            "example": list(self.example),
        }

    @staticmethod
    def from_dict(d):
        return Segment(
            idx=d["idx"],
            start_sec=d["start_sec"], end_sec=d["end_sec"],
            start_bar=d["start_bar"], end_bar=d["end_bar"],
            chord=Chord.from_dict(d["chord"]),
            candidates=[ScaleOption.from_dict(c) for c in d.get("candidates", [])],
            active=d.get("active", 0), degree=d.get("degree", ""),
            is_detour=d.get("is_detour", False),
            example=list(d.get("example", [])),
        )


@dataclass
class Timeline:
    audio_ref: str
    bpm: float
    time_sig: str
    key: str
    key_root: int
    loop_len: int
    segments: list[Segment] = field(default_factory=list)
    available_scales: list[str] = field(default_factory=list)  # 등장 스케일 '종류'
    title: str = ""
    content_span: tuple[float, float] = (0.0, 0.0)
    # 스케일 종류당 1개 리프(상대값, 루트0 기준). 코드 근음으로 이조해 재생(§8).
    # { kind: {notes:[{midi,beat_pos,dur_beats}], note_set:[pc], chord_tones:[pc], n_bars} }
    scale_riffs: dict = field(default_factory=dict)

    # ── 재생 중 룩업 ─────────────────────────────────────────────
    def beat_sec(self) -> float:
        return 60.0 / self.bpm if self.bpm > 0 else 0.5

    def time_sig_beats(self) -> int:
        """박자표의 분자(마디당 박). 예 '4/4' → 4. 파싱 실패 시 4."""
        try:
            return max(1, int(str(self.time_sig).split("/")[0]))
        except (ValueError, IndexError):
            return 4

    def segment_at(self, t: float) -> Segment | None:
        for seg in self.segments:
            if seg.start_sec <= t < seg.end_sec:
                return seg
        if self.segments and t >= self.segments[-1].end_sec:
            return self.segments[-1]
        return self.segments[0] if self.segments else None

    def segment_index_at(self, t: float) -> int:
        for i, seg in enumerate(self.segments):
            if seg.start_sec <= t < seg.end_sec:
                return i
        return len(self.segments) - 1 if self.segments else -1

    def next_segment(self, seg: Segment | None) -> Segment | None:
        if seg is None:
            return None
        nxt = seg.idx + 1
        return self.segments[nxt] if 0 <= nxt < len(self.segments) else None

    def total_bars(self) -> int:
        return max((s.end_bar for s in self.segments), default=0)

    def segment_for_bar(self, bar: int) -> Segment | None:
        for seg in self.segments:
            if seg.start_bar <= bar < seg.end_bar:
                return seg
        return None

    def total_sec(self) -> float:
        return self.segments[-1].end_sec if self.segments else 0.0

    def content_end(self) -> float:
        cs, ce = self.content_span
        return ce if ce > cs else self.total_sec()

    def apply_kind(self, kind: str):
        """가능한 모든 구간에 이 종류 스케일을 적용(통일)."""
        for seg in self.segments:
            seg.set_active_by_kind(kind)

    # ── 직렬화 ───────────────────────────────────────────────────
    def to_dict(self):
        return {
            "audio_ref": self.audio_ref, "bpm": self.bpm, "time_sig": self.time_sig,
            "key": self.key, "key_root": self.key_root, "loop_len": self.loop_len,
            "title": self.title, "content_span": list(self.content_span),
            "available_scales": list(self.available_scales),
            "scale_riffs": self.scale_riffs,
            "segments": [s.to_dict() for s in self.segments],
        }

    @staticmethod
    def from_dict(d):
        tl = Timeline(
            audio_ref=d["audio_ref"], bpm=d["bpm"], time_sig=d["time_sig"],
            key=d["key"], key_root=d["key_root"], loop_len=d["loop_len"],
            title=d.get("title", ""),
            content_span=tuple(d.get("content_span", [0.0, 0.0])),
            available_scales=list(d.get("available_scales", [])),
            scale_riffs=d.get("scale_riffs", {}),
        )
        tl.segments = [Segment.from_dict(s) for s in d["segments"]]
        return tl

    def save_json(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def load_json(path: str) -> "Timeline":
        with open(path, "r", encoding="utf-8") as f:
            return Timeline.from_dict(json.load(f))
