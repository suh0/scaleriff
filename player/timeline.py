"""세션 타임라인 — 앱 전역 단일 상태 (정의서 §5).

원칙(§4): 모든 분석·생성은 빌드(+보정) 단계에서 한 번에 구워(pre-bake) 이 타임라인을
만들고, 화면들은 재생/룩업만 하는 뷰다(상태를 소유하지 않음). 재생/스크럽 중 재분석 없음.

각 코드 구간(Segment)은 후보 스케일(candidates) + active 인덱스로 적용 스케일을 고르고
(현재는 후보 1개), seg.example에 그 구간에 배치된 리프 음(§8)을 담는다.
스케일 종류당 1개의 리프 원본은 Timeline.scale_riffs(상대값)에 있다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import bisect
import os
import tempfile
import math

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
    # ── 마디 격자·보정(§3.5) ────────────────────────────────────
    bar_times: list[float] = field(default_factory=list)  # 마디 시작 시각(+끝)
    loop_phase: int = 0        # 감지 루프 시작 마디 오프셋
    split_point: int = 60      # 왼손(C3~B3)/오른손(C4~B5) 존 분할 MIDI(C4 고정)
    # 사용자 정의 루프 — 코드배열표에서 마디 2개 선택으로 생성(§6).
    # [{"name": str, "start_bar": int, "end_bar": int(포함), "on": bool}, …]
    loops: list = field(default_factory=list)
    # ── MIR 원자료(마디선 보정 §3.5 2차 — 재격자화 재료, MIR 재실행 없음) ──
    beat_times: list[float] = field(default_factory=list)   # 비트 시각
    chord_spans: list = field(default_factory=list)         # [[start,end,name], …]
    wav_ref: str = ""          # 분석용 모노 WAV 경로(파형 표시용, 캐시)
    key_override: bool = False  # 직접 선택한 키는 재격자화에서 자동 변경하지 않음
    chord_overrides: list = field(default_factory=list)  # [원본 시작초, 끝초, 수동 코드]
    timing_override: bool = False  # BPM 직접 보정 시에는 균등 격자 사용
    analysis_info: dict = field(default_factory=dict)
    model_info: dict = field(default_factory=dict)
    practice_history: list = field(default_factory=list)

    def beat_grid(self) -> list[float]:
        """마디 앵커와 검출 비트를 함께 쓰는 원본 오디오 시간축."""
        if len(self.bar_times) < 2:
            return []
        out = []
        beats = self.time_sig_beats()
        raw = [] if self.timing_override else self.beat_times
        for start, end in zip(self.bar_times, self.bar_times[1:]):
            inner = [t for t in raw if start + 1e-5 < t < end - 1e-5]
            out.extend([start] + (inner if len(inner) == beats - 1 else
                                  [start + (end - start) * i / beats
                                   for i in range(1, beats)]))
        return out + [self.bar_times[-1]]

    def beat_at(self, sec: float) -> float:
        grid = self.beat_grid()
        if len(grid) < 2:
            return sec / self.beat_sec()
        i = max(0, min(len(grid) - 2, bisect.bisect_right(grid, sec) - 1))
        return i + (sec - grid[i]) / (grid[i + 1] - grid[i])

    def time_at_beat(self, beat: float) -> float:
        grid = self.beat_grid()
        if len(grid) < 2:
            return beat * self.beat_sec()
        i = max(0, min(len(grid) - 2, int(beat // 1)))
        return grid[i] + (beat - i) * (grid[i + 1] - grid[i])

    def beats_between(self, start: float, end: float) -> float:
        return self.beat_at(end) - self.beat_at(start)

    def effective_chord_spans(self) -> list:
        base = self.chord_spans or [[s.start_sec, s.end_sec, s.chord.name]
                                    for s in self.segments]
        if not base:
            return []
        lo, hi = base[0][0], base[-1][1]
        bounds = sorted({lo, hi} | {max(lo, min(hi, t))
                                   for row in base + self.chord_overrides for t in row[:2]})
        out = []
        for start, end in zip(bounds, bounds[1:]):
            mid = (start + end) / 2
            name = next((r[2] for r in reversed(self.chord_overrides)
                         if r[0] <= mid < r[1]), None)
            if name is None:
                name = next((r[2] for r in base if r[0] <= mid < r[1]), "N")
            if out and out[-1][2] == name:
                out[-1][1] = end
            else:
                out.append([start, end, name])
        return out

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
        return None

    def segment_index_at(self, t: float) -> int:
        for i, seg in enumerate(self.segments):
            if seg.start_sec <= t < seg.end_sec:
                return i
        if self.segments and t >= self.segments[-1].end_sec:
            return len(self.segments) - 1
        return -1

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

    # ── 직렬화 ───────────────────────────────────────────────────
    def to_dict(self):
        return {
            "schema_version": 2,
            "audio_ref": self.audio_ref, "bpm": self.bpm, "time_sig": self.time_sig,
            "key": self.key, "key_root": self.key_root, "loop_len": self.loop_len,
            "title": self.title, "content_span": list(self.content_span),
            "available_scales": list(self.available_scales),
            "scale_riffs": self.scale_riffs,
            "bar_times": list(self.bar_times),
            "loop_phase": self.loop_phase,
            "split_point": self.split_point,
            "loops": [dict(l) for l in self.loops],
            "beat_times": list(self.beat_times),
            "chord_spans": [list(c) for c in self.chord_spans],
            "wav_ref": self.wav_ref,
            "key_override": self.key_override,
            "chord_overrides": [list(row) for row in self.chord_overrides],
            "timing_override": self.timing_override,
            "analysis_info": dict(self.analysis_info), "model_info": dict(self.model_info),
            "practice_history": list(self.practice_history),
            "segments": [s.to_dict() for s in self.segments],
        }

    @staticmethod
    def from_dict(d):
        if not isinstance(d, dict):
            raise ValueError("세션은 JSON 객체여야 합니다")
        if d.get("schema_version", 1) not in (1, 2):
            raise ValueError("지원하지 않는 세션 버전입니다")
        if not math.isfinite(float(d["bpm"])) or float(d["bpm"]) <= 0:
            raise ValueError("세션 BPM이 올바르지 않습니다")
        for key in ("bar_times", "beat_times"):
            times = d.get(key, [])
            if (not isinstance(times, list) or any(not isinstance(t, (int, float))
                    or not math.isfinite(t) for t in times)
                    or any(a >= b for a, b in zip(times, times[1:]))):
                raise ValueError(f"{key}는 유한하고 증가하는 시간 목록이어야 합니다")
        for seg in d.get("segments", []):
            if (not isinstance(seg, dict) or not all(isinstance(seg.get(k), (int, float))
                    and math.isfinite(seg[k]) for k in ("start_sec", "end_sec"))
                    or seg["end_sec"] <= seg["start_sec"]):
                raise ValueError("코드 구간의 시작/끝이 올바르지 않습니다")
        tl = Timeline(
            audio_ref=d["audio_ref"], bpm=d["bpm"], time_sig=d["time_sig"],
            key=d["key"], key_root=d["key_root"], loop_len=d["loop_len"],
            title=d.get("title", ""),
            content_span=tuple(d.get("content_span", [0.0, 0.0])),
            available_scales=list(d.get("available_scales", [])),
            scale_riffs=d.get("scale_riffs", {}),
            bar_times=list(d.get("bar_times", [])),
            loop_phase=d.get("loop_phase", 0),
            split_point=d.get("split_point", 60),
            loops=[dict(l) for l in d.get("loops", [])],
            beat_times=list(d.get("beat_times", [])),
            chord_spans=[list(c) for c in d.get("chord_spans", [])],
            wav_ref=d.get("wav_ref", ""),
            key_override=d.get("key_override", False),
            chord_overrides=[list(row) for row in d.get("chord_overrides", [])],
            timing_override=d.get("timing_override", False),
            analysis_info=dict(d.get("analysis_info", {})),
            model_info=dict(d.get("model_info", {})),
            practice_history=list(d.get("practice_history", [])),
        )
        tl.segments = [Segment.from_dict(s) for s in d["segments"]]
        return tl

    def save_json(self, path: str):
        path = os.path.abspath(path)
        folder = os.path.dirname(path)
        payload = self.to_dict()
        payload["media_refs"] = {}
        for name in ("audio_ref", "wav_ref"):
            value = getattr(self, name)
            if value:
                try:
                    payload["media_refs"][name] = os.path.relpath(value, folder)
                except ValueError:  # Windows 다른 드라이브
                    pass
        fd, temporary = tempfile.mkstemp(prefix=".session_", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)

    @staticmethod
    def load_json(path: str) -> "Timeline":
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            raise ValueError("세션은 JSON 객체여야 합니다")
        for name, relative in payload.get("media_refs", {}).items():
            if name in ("audio_ref", "wav_ref") and not os.path.isfile(payload.get(name, "")):
                candidate = os.path.abspath(os.path.join(os.path.dirname(path), relative))
                if os.path.isfile(candidate):
                    payload[name] = candidate
        return Timeline.from_dict(payload)
