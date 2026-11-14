#!/usr/bin/env python3
"""The one check entry point, as in hermes-finance: `check.py ci` runs the
offline suite; `check.py full` adds the contribution and spelling gates.

`full` runs each gate for real and exits with the first failing gate's
status:

- offline tests: the pytest suite, exactly as `ci` runs it;
- spelling: scripts/check_us_spelling.py against a base ref — the
  --base value when given, else $HERMES_LEGAL_CHECK_BASE, else
  origin/main. When no base ref exists locally the gate is skipped with
  a printed reason rather than run against nothing;
- contribution: scripts/check_contribution.py, when PR metadata is
  supplied with --metadata or $CHECK_CONTRIBUTION_METADATA (a JSON file
  with "body" and "files", the shape .github/workflows/contribution.yml
  builds). A plain local or nightly run has no pull request to check, so
  without metadata the gate is skipped with a printed reason.

Usage: check.py [ci|full] [--base REF] [--metadata FILE]
"""
import os
import subprocess
import sys

SPELLING_BASE_ENV = "HERMES_LEGAL_CHECK_BASE"
METADATA_ENV = "CHECK_CONTRIBUTION_METADATA"
DEFAULT_SPELLING_BASE = "origin/main"


def run(*args):
    return subprocess.call(args)


def _ref_exists(ref):
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        check=False).returncode == 0


def _option(argv, name):
    if name in argv:
        index = argv.index(name)
        if index + 1 < len(argv):
            return argv[index + 1]
    return None


def main(argv=None, runner=None, ref_exists=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    runner = run if runner is None else runner
    ref_exists = _ref_exists if ref_exists is None else ref_exists
    mode = argv[0] if argv else "ci"
    if mode not in ("ci", "full"):
        print(f"usage: check.py [ci|full] [--base REF] [--metadata FILE]; "
              f"unknown mode {mode!r}", file=sys.stderr)
        return 2
    rc = runner(sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider")
    if rc or mode == "ci":
        return rc
    base = (_option(argv, "--base") or os.environ.get(SPELLING_BASE_ENV)
            or DEFAULT_SPELLING_BASE)
    if ref_exists(base):
        rc = runner(sys.executable, "scripts/check_us_spelling.py", "--base", base)
        if rc:
            return rc
    else:
        print(f"spelling gate skipped: base ref {base!r} is not available "
              f"locally; fetch it or pass --base REF")
    metadata = _option(argv, "--metadata") or os.environ.get(METADATA_ENV)
    if metadata:
        return runner(sys.executable, "scripts/check_contribution.py",
                      "--metadata", metadata, "--root", ".")
    print(f"contribution gate skipped: no PR metadata supplied; pass "
          f"--metadata FILE or set ${METADATA_ENV} to a JSON file with "
          f"'body' and 'files'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
