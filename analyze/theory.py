"""음악 이론 유틸 — 음이름/피치클래스, 코드 파싱, 다이아토닉, 코드-스케일.

기존 piano-scale-trainer의 scale_db/enharmonic 개념을 흡수하고,
브리프 §12가 언급한 chord_function_analyzer(코드 파싱·슬래시 코드·패턴)를 새로 작성한다.

규약:
- pitch class(pc): 0~11 정수. C=0, C#=1, ... B=11.
- 코드 root는 pc 정수, quality는 문자열 태그.
"""
from __future__ import annotations
from dataclasses import dataclass

# ── 음이름 ↔ pitch class ──────────────────────────────────────────────
NOTE_TO_PC = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "Fb": 4,
    "E#": 5, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9,
    "A#": 10, "Bb": 10, "B": 11, "Cb": 11, "B#": 0,
}
# 표시용 기본 음이름 (샤프 표기)
PC_TO_NAME = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_to_pc(note: str) -> int:
    note = note.strip()
    if note in NOTE_TO_PC:
        return NOTE_TO_PC[note]
    raise ValueError(f"알 수 없는 음이름: {note!r}")


def pc_name(pc: int) -> str:
    return PC_TO_NAME[pc % 12]


# ── 음정 공식 (root 기준 반음 오프셋) ─────────────────────────────────
# 스케일 (모드)
SCALE_INTERVALS = {
    "major":      [0, 2, 4, 5, 7, 9, 11],   # = ionian
    "ionian":     [0, 2, 4, 5, 7, 9, 11],
    "dorian":     [0, 2, 3, 5, 7, 9, 10],
    "phrygian":   [0, 1, 3, 5, 7, 8, 10],
    "lydian":     [0, 2, 4, 6, 7, 9, 11],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "aeolian":    [0, 2, 3, 5, 7, 8, 10],   # = natural minor
    "minor":      [0, 2, 3, 5, 7, 8, 10],
    "locrian":    [0, 1, 3, 5, 6, 8, 10],
    # 게이트용 축약 스케일
    "major_pentatonic": [0, 2, 4, 7, 9],
    "minor_pentatonic": [0, 3, 5, 7, 10],
}

# 코드 quality → 구성 음정(코드톤) & 어울리는 코드-스케일(모드 이름)
# 코드-스케일: 비다이아토닉 로컬 디투어(§5.3)에서 사용.
CHORD_SPECS = {
    # quality: (chord_tone_intervals, chord_scale_mode)
    "maj":   ([0, 4, 7],        "major"),
    "maj7":  ([0, 4, 7, 11],    "major"),
    "maj6":  ([0, 4, 7, 9],     "major"),
    "min":   ([0, 3, 7],        "dorian"),
    "m7":    ([0, 3, 7, 10],    "dorian"),
    "m6":    ([0, 3, 7, 9],     "dorian"),
    "m7b5":  ([0, 3, 6, 10],    "locrian"),
    "dim":   ([0, 3, 6],        "locrian"),
    "dim7":  ([0, 3, 6, 9],     "locrian"),
    "dom7":  ([0, 4, 7, 10],    "mixolydian"),   # 도미넌트 → 믹솔리디안
    "7":     ([0, 4, 7, 10],    "mixolydian"),
    "aug":   ([0, 4, 8],        "lydian"),
    "sus4":  ([0, 5, 7],        "mixolydian"),
    "sus2":  ([0, 2, 7],        "mixolydian"),
}

# 대표 펜타토닉(난이도 '쉬움' 게이트): quality → 펜타토닉 종류
PENTATONIC_FOR_QUALITY = {
    "maj": "major_pentatonic", "maj7": "major_pentatonic", "maj6": "major_pentatonic",
    "dom7": "major_pentatonic", "7": "major_pentatonic",
    "sus4": "major_pentatonic", "sus2": "major_pentatonic", "aug": "major_pentatonic",
    "min": "minor_pentatonic", "m7": "minor_pentatonic", "m6": "minor_pentatonic",
    "m7b5": "minor_pentatonic", "dim": "minor_pentatonic", "dim7": "minor_pentatonic",
}


@dataclass
class Chord:
    name: str       # 표시용, 예 "Dm7"
    root: int       # pc 0~11
    quality: str    # CHORD_SPECS 키
    bass: int | None = None  # 슬래시 코드 베이스 pc (없으면 None)

    def chord_tones(self) -> list[int]:
        ivs, _ = CHORD_SPECS.get(self.quality, CHORD_SPECS["maj"])
        return sorted({(self.root + i) % 12 for i in ivs})

    def chord_scale(self) -> list[int]:
        """코드-스케일(로컬 디투어용) pc 집합."""
        _, mode = CHORD_SPECS.get(self.quality, CHORD_SPECS["maj"])
        return scale_pcs(self.root, mode)

    def pentatonic(self) -> list[int]:
        mode = PENTATONIC_FOR_QUALITY.get(self.quality, "major_pentatonic")
        return scale_pcs(self.root, mode)

    def to_dict(self) -> dict:
        return {"name": self.name, "root": self.root,
                "quality": self.quality, "bass": self.bass}

    @staticmethod
    def from_dict(d: dict) -> "Chord":
        return Chord(d["name"], d["root"], d["quality"], d.get("bass"))


def scale_pcs(root: int, mode: str) -> list[int]:
    ivs = SCALE_INTERVALS.get(mode, SCALE_INTERVALS["major"])
    return sorted({(root + i) % 12 for i in ivs})


# ── 코드 이름 파싱 (슬래시 코드 처리 포함) ───────────────────────────
# 긴 접미사부터 매칭해야 함 ("maj7" 먼저, "maj" 나중)
_QUALITY_SUFFIXES = [
    ("maj7", "maj7"), ("M7", "maj7"), ("Δ7", "maj7"), ("Δ", "maj7"),
    ("maj9", "maj7"), ("M9", "maj7"),
    ("m7b5", "m7b5"), ("ø", "m7b5"), ("min7b5", "m7b5"),
    ("dim7", "dim7"), ("°7", "dim7"),
    ("dim", "dim"), ("°", "dim"),
    ("min7", "m7"), ("m7", "m7"), ("-7", "m7"),
    ("min6", "m6"), ("m6", "m6"),
    ("min", "min"), ("m", "min"), ("-", "min"),
    ("maj6", "maj6"), ("6", "maj6"),
    ("sus4", "sus4"), ("sus2", "sus2"), ("sus", "sus4"),
    ("aug", "aug"), ("+", "aug"),
    ("7", "dom7"), ("9", "dom7"), ("11", "dom7"), ("13", "dom7"),
    ("maj", "maj"), ("M", "maj"),
]


def parse_chord(name: str) -> Chord:
    """'Dm7', 'C/E', 'F#maj7', 'Bb7' 등을 Chord로 파싱.

    인식 실패 시 maj 트라이어드로 폴백.
    """
    raw = name.strip()
    if not raw or raw in ("N", "N.C.", "NC", "none"):
        # 무화음 — C maj 폴백 (호출측에서 거의 안 씀)
        return Chord(raw or "N", 0, "maj")

    work = raw
    bass = None
    if "/" in work:
        work, bass_str = work.split("/", 1)
        try:
            bass = note_to_pc(bass_str.strip())
        except ValueError:
            bass = None

    # root 음이름 (2글자 우선: C#, Bb)
    root = None
    rlen = 0
    if len(work) >= 2 and work[:2] in NOTE_TO_PC:
        root, rlen = NOTE_TO_PC[work[:2]], 2
    elif work[:1] in NOTE_TO_PC:
        root, rlen = NOTE_TO_PC[work[:1]], 1
    if root is None:
        return Chord(raw, 0, "maj")

    suffix = work[rlen:]
    quality = "maj"  # 접미사 없으면 메이저
    if suffix:
        matched = False
        for tok, q in _QUALITY_SUFFIXES:
            if suffix.startswith(tok):
                quality = q
                matched = True
                break
        if not matched:
            quality = "maj"

    return Chord(raw, root, quality, bass)


# ── 코드 진행 패턴 인식 (상단 배너용, 예 ii-V-I) ─────────────────────
def roman_degrees(chords: list[Chord], key_root: int) -> list[str]:
    """키 기준 각 코드의 로마숫자 도수(간이)."""
    deg_map = {0: "I", 2: "ii", 4: "iii", 5: "IV", 7: "V", 9: "vi", 11: "vii"}
    out = []
    for c in chords:
        rel = (c.root - key_root) % 12
        base = deg_map.get(rel, "?")
        if c.quality in ("min", "m7", "m6"):
            base = base.lower()
        elif c.quality in ("dim", "dim7", "m7b5"):
            base = base.lower() + "°"
        out.append(base)
    return out


def detect_pattern(chords: list[Chord], key_root: int) -> str | None:
    """대표 진행 패턴 라벨 (없으면 None)."""
    degs = [d.lower().rstrip("°") for d in roman_degrees(chords, key_root)]
    seq = "-".join(degs)
    patterns = {
        "ii-v-i": "ii–V–I",
        "i-vi-ii-v": "I–vi–ii–V",
        "i-iv-v": "I–IV–V",
        "i-v-vi-iv": "I–V–vi–IV (팝 4코드)",
        "vi-iv-i-v": "vi–IV–I–V",
        "ii-v": "ii–V",
    }
    for pat, label in patterns.items():
        if pat in seq:
            return label
    return None


# ── 기능 라벨 (근음/3도/9도 등, §9.2 별도 라벨) ─────────────────────
_DEGREE_LABEL = {
    0: "근음", 1: "♭9", 2: "9도", 3: "♭3/＃9", 4: "3도", 5: "4도/11",
    6: "＃11/♭5", 7: "5도", 8: "♭6/＃5", 9: "6도/13", 10: "♭7", 11: "7도",
}


def function_label(pc: int, chord: Chord) -> str:
    """코드 근음 기준 pc의 기능 이름."""
    rel = (pc - chord.root) % 12
    return _DEGREE_LABEL.get(rel, "")


# ── 코드별 스케일 이름 산출 (정의서 §3, §5: 다이아토닉=키의 해당 모드) ───
# 메이저 키 안에서 root 오프셋(반음) → 모드 이름
_MAJOR_OFFSET_TO_MODE = {
    0: "ionian", 2: "dorian", 4: "phrygian", 5: "lydian",
    7: "mixolydian", 9: "aeolian", 11: "locrian",
}
# 표시용 한글 모드 이름
MODE_KR = {
    "ionian": "아이오니안", "major": "아이오니안",
    "dorian": "도리안", "phrygian": "프리지안", "lydian": "리디안",
    "mixolydian": "믹솔리디안", "aeolian": "에올리안", "minor": "에올리안",
    "locrian": "로크리안",
}


def scale_kind_for(chord: Chord, home_root: int, home_mode: str,
                   is_detour: bool) -> str:
    """코드에 배정된 스케일 '종류'(예 '도리안'). 시작음 무관(정의서 통일 §).

    다이아토닉: 홈 키 음 모음을 코드 root에서 시작하는 모드(같은 7음, 시작점만 다름).
    비다이아토닉(디투어): 코드 품질의 코드-스케일 모드.
    """
    if is_detour:
        _, mode = CHORD_SPECS.get(chord.quality, CHORD_SPECS["maj"])
    else:
        major_root = home_root if home_mode == "major" else (home_root + 3) % 12
        off = (chord.root - major_root) % 12
        mode = _MAJOR_OFFSET_TO_MODE.get(off)
        if mode is None:
            _, mode = CHORD_SPECS.get(chord.quality, CHORD_SPECS["maj"])
    return MODE_KR.get(mode, mode)


def scale_name_for(chord: Chord, home_root: int, home_mode: str,
                   is_detour: bool) -> str:
    """코드에 배정된 스케일 이름(예 'D 도리안')."""
    return f"{pc_name(chord.root)} {scale_kind_for(chord, home_root, home_mode, is_detour)}"


def diatonic_option(chord: Chord, home_root: int, home_mode: str,
                    is_detour: bool, note_set: list[int]) -> dict:
    """코드에 배정되는 **단일** 다이아토닉 스케일 후보(§3).

    7다이아토닉 모드 중 코드의 키-도수가 결정하는 정확히 하나(시작음=코드 근음).
    음악적으로 한 코드엔 한 스케일이므로 후보는 항상 1개 — 선택 여지 없음.
    각 항목: {kind, root, name, note_set}. root는 코드 근음(도수 계산용).
    """
    return {
        "kind": scale_kind_for(chord, home_root, home_mode, is_detour),
        "root": chord.root,
        "name": scale_name_for(chord, home_root, home_mode, is_detour),
        "note_set": sorted(set(note_set)),
    }


def degree_for(chord: Chord, key_root: int) -> str:
    """키 기준 단일 코드의 로마숫자 도수(예 'ii')."""
    return roman_degrees([chord], key_root)[0]


# ── 건반 표시용 도수 숫자 (코드/스케일 root 기준) ─────────────────────
_DEGREE_NUM = {
    0: "1", 1: "♭2", 2: "2", 3: "♭3", 4: "3", 5: "4",
    6: "♯4", 7: "5", 8: "♭6", 9: "6", 10: "♭7", 11: "7",
}


def degree_number(pc: int, root: int) -> str:
    """root 기준 pc의 스케일 도수 숫자(예 1·3·5). 건반 위 표시용."""
    return _DEGREE_NUM.get((pc - root) % 12, "")


if __name__ == "__main__":
    for nm in ["Dm7", "C/E", "F#maj7", "Bb7", "Em7b5", "Csus4", "A", "G7"]:
        c = parse_chord(nm)
        print(f"{nm:8} -> root={pc_name(c.root):3} q={c.quality:6} "
              f"tones={[pc_name(p) for p in c.chord_tones()]} bass={c.bass}")
    chs = [parse_chord(x) for x in ["Dm7", "G7", "Cmaj7"]]
    print("pattern:", detect_pattern(chs, key_root=0))
