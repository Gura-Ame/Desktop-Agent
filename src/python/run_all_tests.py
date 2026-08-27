import os
import sys
import subprocess
from pathlib import Path

tests_dir = Path(__file__).resolve().parent / "tests"
test_files = sorted(tests_dir.glob("test_*.py"))
passed = 0
failed = []

for tf in test_files:
    p = subprocess.run(
        [sys.executable, str(tf)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode == 0:
        passed += 1
        print(f"[PASS] {os.path.basename(tf)}")
    else:
        failed.append((tf, p.stdout, p.stderr))
        print(f"[FAIL] {os.path.basename(tf)}")

print(f"\n==============================")
print(f"Result: {passed}/{len(test_files)} passed")
print(f"==============================")

if failed:
    for tf, out, err in failed:
        print(f"\n--- Output of {tf} ---")
        print(out)
        print(err)
    sys.exit(1)
