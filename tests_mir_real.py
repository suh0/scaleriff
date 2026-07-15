"""실제 백킹트랙으로 코드 인식 정확도 측정(검증 가능한 진행 ground-truth 대조).

각 트랙: (URL, 키, 기대 진행[루프 1주기, 마디당 1코드]).
검출된 진행을 루프 1주기로 접어 마디별 (근음, 품질군) 일치율을 출력.
"""
import os, sys
os.environ.setdefault("PYTHONUTF8", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ingest.audio_source import resolve_audio
from ingest.mir_extract import get_backend
from analyze.theory import parse_chord
from ml.representation import quality_family

# (이름, URL, 키, 기대 진행[마디 단위, 루프 1주기])
TRACKS = [
    ("2-5-1 C Major", "https://www.youtube.com/watch?v=ASrPNZlR8FM",
     "C major", ["Dm7", "G7", "Cmaj7", "Cmaj7"]),
    ("Ailee 손대지마", "https://www.youtube.com/watch?v=opbMk58n6sA",
     "G minor", ["Gm", "Bb", "Cm", "D"]),
]


def _qf(name):
    return quality_family(parse_chord(name).quality)


def _root(name):
    return parse_chord(name).root


def measure(name, url, key, expected):
    print(f"\n{'='*64}\n[{name}] expected {expected}  key={key}")
    wav, original, title = resolve_audio(url)
    res = get_backend().analyze(wav)   # auto: madmom 설치 시 학습 모델, 없으면 librosa
    print(f"  title={title!r}  BPM={res.bpm:.0f}  key={res.key}  "
          f"bars/loop≈{len(expected)}  chords={len(res.chords)}")
    # 원시 구조 관찰: 검출된 코드 스팬(처음 16개)
    print("  raw spans:", " | ".join(
        f"{c.name}({c.end_sec-c.start_sec:.1f}s)" for c in res.chords[:16]))
    # 검출 코드를 마디 격자로: content_span 안에서 bar_sec 단위로 샘플
    bar_sec = res.beats_per_bar * 60.0 / res.bpm
    cs, ce = res.content_span if res.content_span[1] > res.content_span[0] else (0, res.duration)
    # 마디별 검출 코드(마디 중앙 시각의 코드)
    detected = []
    t = cs + bar_sec * 0.5
    while t < ce:
        ch = next((c.name for c in res.chords if c.start_sec <= t < c.end_sec), None)
        detected.append(ch)
        t += bar_sec
    # 루프 1주기로 접어 다수결
    n = len(expected)
    folded = []
    for i in range(n):
        col = [detected[j] for j in range(i, len(detected), n) if detected[j]]
        if not col:
            folded.append(None); continue
        folded.append(max(set(col), key=col.count))
    # 일치율(근음+품질군)
    hits_root = hits_full = 0
    print("  bar | expected | detected(folded)")
    for i in range(n):
        exp, got = expected[i], folded[i]
        rok = got and _root(got) == _root(exp)
        fok = rok and _qf(got) == _qf(exp)
        hits_root += bool(rok); hits_full += bool(fok)
        mark = "OK" if fok else ("~root" if rok else "MISS")
        print(f"   {i+1}  | {exp:8} | {str(got):8}  {mark}")
    print(f"  => root {hits_root}/{n}, full {hits_full}/{n}")
    return hits_root, hits_full, n


if __name__ == "__main__":
    tot_r = tot_f = tot_n = 0
    for tr in TRACKS:
        r, f, n = measure(*tr)
        tot_r += r; tot_f += f; tot_n += n
    print(f"\nTOTAL: root {tot_r}/{tot_n}, full {tot_f}/{tot_n}")
