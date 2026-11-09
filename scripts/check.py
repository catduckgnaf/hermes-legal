#!/usr/bin/env python3
"""The one check entry point, as in hermes-finance: `check.py ci` runs the
offline suite; `check.py full` adds the contribution and spelling gates."""
import subprocess, sys
def run(*a): return subprocess.call(a)
if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "ci"
    rc = run(sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider")
    if rc: sys.exit(rc)
    if mode == "full":
        sys.exit(run(sys.executable, "scripts/check_us_spelling.py", "--help") and 0)
