#!/usr/bin/env python3
"""전체 파이프라인 실행: 수집 → 정규화 → 사이트 생성 → 검증."""
import subprocess
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STEPS = ["fetch.py", "normalize.py", "build_site.py", "check_site.py"]

for step in STEPS:
    print(f"\n=== {step} ===", flush=True)
    result = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", step)], cwd=ROOT)
    if result.returncode != 0:
        print(f"FAILED at {step} (exit {result.returncode})")
        sys.exit(result.returncode)
print("\nall steps passed")
