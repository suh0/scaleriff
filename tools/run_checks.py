"""모든 기존 스크립트와 unittest를 실제 진입점으로 실행한다."""
import argparse
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", action="store_true", help="YouTube 실제 다운로드 평가도 실행")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONUTF8="1", QT_QPA_PLATFORM="offscreen", QT_MEDIA_BACKEND="ffmpeg")
    paths = sorted(root.glob("tests_*.py"))
    # tests_analyze의 입력을 만드는 기존 합성 MIR 스크립트를 먼저 실행한다.
    first = root / "tests_mir.py"
    paths = [first] + [p for p in paths if p != first]
    failed = []
    count = 0
    for path in paths:
        if path.name == "tests_mir_real.py" and not args.network:
            continue
        result = subprocess.run([sys.executable, str(path)], cwd=root, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", timeout=180)
        count += 1
        print(f"{'PASS' if result.returncode == 0 else 'FAIL'} {path.name}", flush=True)
        if result.returncode:
            print(result.stdout, flush=True)
            failed.append(path.name)
    print(f"CHECKS {count - len(failed)}/{count}; network={'on' if args.network else 'not run'}")
    return bool(failed)


if __name__ == "__main__":
    sys.exit(main())
