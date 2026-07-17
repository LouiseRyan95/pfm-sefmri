#!/usr/bin/env python3
"""Check or apply the NVD global-run compatibility patch.

The repository's legacy coreg/headmotion/aCompCor loops infer run numbers from
directory counts. NVD intentionally uses run_12..run_51 in later sessions, so
those loops must enumerate the actual directory names instead.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def corrected_patch(repo: Path) -> bytes:
    path = repo / "patches" / "nvd_global_run_numbers_v2.patch"
    text = path.read_text(encoding="utf-8")
    text = text.replace("@@ -407,7 +416,7 @@", "@@ -407,8 +416,8 @@")
    text = text.replace("@@ -496,11 +505,11 @@", "@@ -496,9 +505,9 @@")
    return text.encode("utf-8")


def git_apply(repo: Path, patch: bytes, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "apply", *args, "-"],
        cwd=repo,
        input=patch,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Enable NVD global run_1..run_51 compatibility")
    parser.add_argument("--apply", action="store_true", help="Apply after a successful check (default: check only)")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    patch = corrected_patch(repo)

    check = git_apply(repo, patch, "--check")
    if check.returncode != 0:
        reverse = git_apply(repo, patch, "--reverse", "--check")
        if reverse.returncode == 0:
            print("NVD global-run compatibility patch is already applied.")
            return 0
        sys.stderr.buffer.write(check.stderr)
        return check.returncode

    if not args.apply:
        print("NVD global-run compatibility patch check passed. Re-run with --apply to modify the modules.")
        return 0

    applied = git_apply(repo, patch)
    if applied.returncode != 0:
        sys.stderr.buffer.write(applied.stderr)
        return applied.returncode
    print("Applied NVD global-run compatibility patch.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
